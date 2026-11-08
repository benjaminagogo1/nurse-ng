"""Exercise migration history as well as the current model metadata."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import enable_sqlite_foreign_keys
from app.models.community import (
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    ContentReport,
    DiscussionFollow,
    DiscussionReplyRead,
)
from app.models.user import User
from app.services.community import (
    add_reply,
    discussion_reply_page,
    discussion_summaries,
    mark_discussion_read,
)


def historical_user(db, **values):
    """Seed the selected old schema without inserting columns introduced later."""
    identifier = uuid.uuid4()
    users = Table("users", MetaData(), autoload_with=db.connection())
    db.execute(users.insert().values(
        id=identifier.hex, status="active", phone_verified=False, mfa_enabled=False,
        is_active=True, is_staff=False, **values,
    ))
    return SimpleNamespace(id=identifier)


def test_fresh_and_dual_head_upgrades_preserve_accounts(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "e8f1a2b3c4d5")
    command.upgrade(config, "a1b2c3d4e5f6")
    engine = create_engine(database_url)
    account_id = uuid.uuid4().hex
    with engine.begin() as connection:
        users = Table("users", MetaData(), autoload_with=connection)
        connection.execute(
            users.insert().values(
                id=account_id,
                phone="+2348012345678",
                hashed_password="historical-hash",
                status="active",
                phone_verified=False,
                mfa_enabled=False,
                is_active=True,
                is_staff=False,
                community_name="Ada",
                community_name_key="ada",
            )
        )
        revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        assert set(revisions) == {
            "e8f1a2b3c4d5",
            "a1b2c3d4e5f6",
        }

    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        account = connection.execute(
            text(
                "SELECT phone, hashed_password, community_name, full_name, account_type "
                "FROM users WHERE id = :id"
            ),
            {"id": account_id},
        ).one()
        assert tuple(account) == ("+2348012345678", "historical-hash", "Ada", "", "nurse")
        assert {"jobs", "job_applications", "direct_messages"} <= set(
            inspect(connection).get_table_names()
        )
    command.downgrade(config, "f9a2b3c4d5e6")
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM users")).scalar_one() == account_id
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()


def test_reply_read_upgrade_preserves_existing_follow_cutoff(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'reply_reads.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "c3d4e5f6a7b8")
    engine = create_engine(database_url)
    cutoff = datetime.now(UTC)
    with Session(engine, expire_on_commit=False) as db:
        author = historical_user(db,
            phone="+2348111111111",
            hashed_password="unused",
            community_name="Author",
            community_name_key="author",
        )
        member = historical_user(
            db, phone="+2348222222222", hashed_password="unused", community_name="Reader",
        )
        topic = db.query(CommunityTopic).one()
        db.flush()
        post = CommunityPost(author_id=author.id, topic_id=topic.id, body="Existing question")
        db.add(post)
        db.flush()
        subscription = DiscussionFollow(user_id=member.id, post_id=post.id, last_read_at=cutoff)
        db.add(subscription)
        # Seed the historical schema, which predates the optional reply-context column.
        historical_replies = Table("community_replies", MetaData(), autoload_with=db.connection())
        db.execute(
            historical_replies.insert(),
            [
                {
                    "id": uuid.uuid4().hex,
                    "post_id": post.id.hex,
                    "author_id": author.id.hex,
                    "body": body,
                    "status": "published",
                    "created_at": created,
                    "removal_reason": "",
                }
                for body, created in [
                    ("Previously read", cutoff - timedelta(seconds=1)),
                    ("Still new", cutoff + timedelta(seconds=1)),
                ]
            ],
        )
        db.commit()
        member_id, post_id, follow_id = member.id, post.id, subscription.id
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        member = db.get(User, member_id)
        post = db.get(CommunityPost, post_id)
        assert db.get(DiscussionFollow, follow_id).last_read_at == cutoff.replace(tzinfo=None)
        assert discussion_summaries(db, [post], member)[post.id]["new_replies"] == 1
        page = discussion_reply_page(db, post, member)
        mark_discussion_read(db, member, post, page.replies)
        assert discussion_summaries(db, [post], member)[post.id]["new_replies"] == 0
    command.downgrade(config, "c3d4e5f6a7b8")
    assert "discussion_reply_reads" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        assert db.get(CommunityPost, post_id).body == "Existing question"
        assert db.get(DiscussionFollow, follow_id).last_read_at == cutoff.replace(tzinfo=None)
    engine.dispose()


@pytest.mark.parametrize("existing_topic", [False, True])
def test_discussion_upgrade_preserves_topics_and_only_initializes_empty_database(
    tmp_path,
    monkeypatch,
    existing_topic,
):
    database_url = f"sqlite:///{tmp_path / 'discussions.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "b2c3d4e5f6a7")
    engine = create_engine(database_url)
    if existing_topic:
        with engine.begin() as connection:
            topics = Table("community_topics", MetaData(), autoload_with=connection)
            connection.execute(
                topics.insert().values(
                    id=uuid.uuid4().hex,
                    name="Existing topic",
                    slug="existing",
                    description="Keep me",
                    is_active=False,
                )
            )
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        topics = connection.execute(text("SELECT name, is_active FROM community_topics")).all()
        expected = [("Existing topic", 0)] if existing_topic else [("General nursing", 1)]
        assert topics == expected
        assert connection.execute(text("SELECT count(*) FROM community_posts")).scalar_one() == 0
        assert "discussion_follows" in inspect(connection).get_table_names()
    command.downgrade(config, "b2c3d4e5f6a7")
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM community_topics")).scalar_one() == 1
    engine.dispose()


def test_reply_context_migration_preserves_replies_reports_and_read_records(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'reply_context.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "d4e5f6a7b8c9")
    engine = create_engine(database_url)
    enable_sqlite_foreign_keys(engine)
    with Session(engine, expire_on_commit=False) as db:
        author = historical_user(db,
            phone="+2348111111111",
            hashed_password="unused",
            community_name="Author",
            community_name_key="author",
        )
        db.flush()
        topic = db.query(CommunityTopic).one()
        post = CommunityPost(author_id=author.id, topic_id=topic.id, body="Keep this discussion")
        db.add(post)
        db.flush()
        original_id = uuid.uuid4()
        historical_replies = Table("community_replies", MetaData(), autoload_with=db.connection())
        db.execute(
            historical_replies.insert().values(
                id=original_id.hex,
                post_id=post.id.hex,
                author_id=author.id.hex,
                body="Keep this original response",
                status="published",
                removal_reason="",
            )
        )
        subscription = DiscussionFollow(
            user_id=author.id, post_id=post.id, last_read_at=datetime.now(UTC)
        )
        db.add(subscription)
        db.flush()
        read = DiscussionReplyRead(follow_id=subscription.id, reply_id=original_id)
        report = ContentReport(
            reporter_id=author.id, reply_id=original_id, reason="spam", details="Keep report"
        )
        db.add_all([read, report])
        db.commit()
        author_id, post_id, follow_id, report_id = author.id, post.id, subscription.id, report.id
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        original = db.get(CommunityReply, original_id)
        assert original.body == "Keep this original response" and original.in_reply_to_id is None
        assert db.get(ContentReport, report_id).reply_id == original_id
        assert db.get(DiscussionReplyRead, (follow_id, original_id)) is not None
        child = add_reply(
            db,
            db.get(User, author_id),
            db.get(CommunityPost, post_id),
            "New targeted response",
            in_reply_to_id=original_id,
        )
        child_id = child.id
        assert child.in_reply_to_id == original_id
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    command.downgrade(config, "d4e5f6a7b8c9")
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT body FROM community_replies WHERE id=:id"),
                {
                    "id": child_id.hex,
                },
            ).scalar_one()
            == "New targeted response"
        )
        assert connection.execute(text("SELECT count(*) FROM discussion_reply_reads")).scalar() == 1
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        assert db.get(CommunityReply, child_id).in_reply_to_id is None
        assert db.get(ContentReport, report_id).reply_id == original_id
    engine.dispose()
