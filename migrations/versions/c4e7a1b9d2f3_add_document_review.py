"""add document review cases and private evidence

Revision ID: c4e7a1b9d2f3
Revises: 8f2c1d4a9b6e
Create Date: 2026-10-21 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e7a1b9d2f3'
down_revision: str | None = '8f2c1d4a9b6e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode keeps the column addition portable to SQLite (DECISIONS L42).
    with op.batch_alter_table('nurse_profiles') as batch_op:
        batch_op.add_column(
            sa.Column('document_reviewed_at', sa.DateTime(timezone=True), nullable=True)
        )

    op.create_table('verification_cases',
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('registration_number', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('decided_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['decided_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['profile_id'], ['nurse_profiles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_verification_cases_created_at'), 'verification_cases', ['created_at'], unique=False)
    op.create_index(op.f('ix_verification_cases_decided_by_user_id'), 'verification_cases', ['decided_by_user_id'], unique=False)
    op.create_index(op.f('ix_verification_cases_profile_id'), 'verification_cases', ['profile_id'], unique=False)

    op.create_table('evidence_documents',
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('storage_name', sa.String(length=64), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['verification_cases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('storage_name')
    )
    op.create_index(op.f('ix_evidence_documents_case_id'), 'evidence_documents', ['case_id'], unique=False)
    op.create_index(op.f('ix_evidence_documents_created_at'), 'evidence_documents', ['created_at'], unique=False)

    op.create_table('evidence_accesses',
    sa.Column('evidence_id', sa.Uuid(), nullable=False),
    sa.Column('accessed_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['accessed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence_documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_evidence_accesses_accessed_by_user_id'), 'evidence_accesses', ['accessed_by_user_id'], unique=False)
    op.create_index(op.f('ix_evidence_accesses_created_at'), 'evidence_accesses', ['created_at'], unique=False)
    op.create_index(op.f('ix_evidence_accesses_evidence_id'), 'evidence_accesses', ['evidence_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_evidence_accesses_evidence_id'), table_name='evidence_accesses')
    op.drop_index(op.f('ix_evidence_accesses_created_at'), table_name='evidence_accesses')
    op.drop_index(op.f('ix_evidence_accesses_accessed_by_user_id'), table_name='evidence_accesses')
    op.drop_table('evidence_accesses')
    op.drop_index(op.f('ix_evidence_documents_created_at'), table_name='evidence_documents')
    op.drop_index(op.f('ix_evidence_documents_case_id'), table_name='evidence_documents')
    op.drop_table('evidence_documents')
    op.drop_index(op.f('ix_verification_cases_profile_id'), table_name='verification_cases')
    op.drop_index(op.f('ix_verification_cases_decided_by_user_id'), table_name='verification_cases')
    op.drop_index(op.f('ix_verification_cases_created_at'), table_name='verification_cases')
    op.drop_table('verification_cases')

    with op.batch_alter_table('nurse_profiles') as batch_op:
        batch_op.drop_column('document_reviewed_at')
