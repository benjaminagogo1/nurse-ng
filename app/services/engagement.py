"""Set the desired like state so retries cannot create duplicates or undo a like."""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.community import CommunityPost, ContentStatus
from app.models.engagement import PostLike
from app.models.reels import Reel
from app.models.user import UserStatus


def like_summaries(db, post_ids, user=None):
    result = {post_id: {"likes": 0, "liked": False} for post_id in post_ids}
    if not result:
        return result
    for post_id, count in db.execute(select(PostLike.post_id, func.count()).where(
        PostLike.post_id.in_(result)
    ).group_by(PostLike.post_id)):
        result[post_id]["likes"] = count
    if user:
        for post_id in db.scalars(select(PostLike.post_id).where(
            PostLike.post_id.in_(result), PostLike.user_id == user.id,
        )):
            result[post_id]["liked"] = True
    return result


def set_like(db, user, post_id, *, liked):
    post = db.get(CommunityPost, post_id)
    reel = db.get(Reel, post_id)
    if (not post or post.status != ContentStatus.PUBLISHED
            or (reel and reel.state != "ready")):
        raise LookupError("This post is no longer available.")
    if not user.is_active or user.status != UserStatus.ACTIVE:
        raise PermissionError("Sign in to like this post.")
    if liked:
        insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
        db.execute(insert(PostLike).values(post_id=post_id, user_id=user.id)
                   .on_conflict_do_nothing(index_elements=["post_id", "user_id"]))
    else:
        db.execute(delete(PostLike).where(
            PostLike.post_id == post_id, PostLike.user_id == user.id,
        ))
    db.commit()
    return like_summaries(db, [post_id], user)[post_id]
