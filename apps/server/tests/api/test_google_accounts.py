from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select

from protohub.accounts import main
from protohub.persistence.auth import AuthenticationRequired, SessionRepository
from protohub.persistence.database import create_session_factory
from protohub.persistence.models import Base, GoogleAccountRow, SessionRow, UserRow

EMAIL = "owner@example.test"
SUBJECT = "google-test-subject"


def bearer(result):
    return "Bearer " + result.token


def test_existing_user_and_email_only_session_are_not_google_membership(factory):
    repo = SessionRepository(factory)
    dev = bearer(repo.login(EMAIL))
    with pytest.raises(AuthenticationRequired):
        repo.login_google(EMAIL, SUBJECT, True)
    repo.add_account(" Owner@Example.Test ")
    google = bearer(repo.login_google(EMAIL, SUBJECT, True))
    assert repo.authenticate(dev).email == EMAIL
    assert repo.authenticate(google, google=True).email == EMAIL
    with pytest.raises(AuthenticationRequired):
        repo.authenticate(dev, google=True)
    with pytest.raises(AuthenticationRequired):
        repo.authenticate(google)
    with factory() as db:
        assert db.get(GoogleAccountRow, EMAIL).subject == SUBJECT
    repo.logout(google)
    with pytest.raises(AuthenticationRequired):
        repo.authenticate(google, google=True)


def test_unbound_third_party_and_subject_conflicts_cannot_issue_sessions(factory):
    repo = SessionRepository(factory)
    repo.add_account(EMAIL)
    with pytest.raises(AuthenticationRequired):
        repo.login_google(EMAIL, SUBJECT, False)
    with factory() as db:
        assert db.get(UserRow, EMAIL) is None
        assert db.get(GoogleAccountRow, EMAIL).subject is None
    repo.add_account(EMAIL, SUBJECT)
    repo.add_account(EMAIL, SUBJECT)
    repo.add_account(EMAIL)
    assert repo.login_google(EMAIL, SUBJECT, False).email == EMAIL
    with pytest.raises(AuthenticationRequired):
        repo.login_google(EMAIL, "another-subject", True)
    with pytest.raises(ValueError):
        repo.add_account(EMAIL, "another-subject")
    with pytest.raises(ValueError):
        repo.add_account("other@example.test", SUBJECT)
    repo.add_account("other@example.test")
    with pytest.raises(AuthenticationRequired):
        repo.login_google("other@example.test", SUBJECT, True)
    with factory() as db:
        assert db.get(GoogleAccountRow, "other@example.test").subject is None
        assert len(list(db.scalars(select(SessionRow)))) == 1


def test_remove_revokes_all_google_sessions_even_across_reprovisioning(factory, clock):
    repo = SessionRepository(factory, clock)
    dev = bearer(repo.login(EMAIL))
    repo.add_account(EMAIL, SUBJECT)
    old = [bearer(repo.login_google(EMAIL, SUBJECT, False)) for _ in range(2)]
    repo.remove_account(EMAIL)
    repo.remove_account(EMAIL)
    with pytest.raises(AuthenticationRequired):
        repo.login_google(EMAIL, SUBJECT, True)
    repo.add_account(EMAIL, SUBJECT)
    for header in old:
        with pytest.raises(AuthenticationRequired):
            repo.authenticate(header, google=True)
    assert repo.authenticate(dev).email == EMAIL
    repo.remove_account(EMAIL)
    with pytest.raises(ValueError):
        repo.add_account(EMAIL, "replacement")
    with factory() as db:
        membership = db.get(GoogleAccountRow, EMAIL)
        assert membership.subject == SUBJECT and membership.active is False
    repo.add_account(EMAIL)
    with pytest.raises(AuthenticationRequired):
        repo.login_google(EMAIL, "replacement", True)
    current = bearer(repo.login_google(EMAIL, SUBJECT, False))
    assert repo.authenticate(current, google=True).email == EMAIL
    clock.advance(24 * 3600)
    with pytest.raises(AuthenticationRequired):
        repo.authenticate(current, google=True)


def test_unbound_invite_can_be_reactivated_but_inactive_membership_rejects_sessions(factory):
    repo = SessionRepository(factory)
    repo.add_account(EMAIL)
    repo.remove_account(EMAIL)
    with pytest.raises(AuthenticationRequired):
        repo.login_google(EMAIL, SUBJECT, True)
    repo.add_account(EMAIL, SUBJECT)
    valid = bearer(repo.login_google(EMAIL, SUBJECT, False))
    assert repo.authenticate(valid, google=True).email == EMAIL
    # Check active membership independently of the CLI's normal session deletion.
    with factory.begin() as db:
        db.get(GoogleAccountRow, EMAIL).active = False
    with pytest.raises(AuthenticationRequired):
        repo.authenticate(valid, google=True)


@pytest.mark.parametrize("subject", ["", " spaced", "x\ny", "ü", "x" * 256])
def test_invalid_subject_is_rejected(factory, subject):
    repo = SessionRepository(factory)
    with pytest.raises(ValueError):
        repo.add_account(EMAIL, subject)
    repo.add_account(EMAIL)
    with pytest.raises(AuthenticationRequired):
        repo.login_google(EMAIL, subject, True)


def test_concurrent_first_login_binds_exactly_one_subject(tmp_path):
    factory = create_session_factory("sqlite:///" + str(tmp_path / "race.db"))
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    repo = SessionRepository(factory)
    repo.add_account(EMAIL)
    barrier = Barrier(2)

    def claim(subject):
        barrier.wait(timeout=10)
        try:
            return bearer(repo.login_google(EMAIL, subject, True))
        except AuthenticationRequired:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            subjects = ["first", "second"]
            results = list(pool.map(claim, subjects))
        assert results.count(None) == 1
        with factory() as db:
            bound = db.get(GoogleAccountRow, EMAIL).subject
            assert results[subjects.index(bound)] is not None
            assert len(list(db.scalars(select(SessionRow)))) == 1
    finally:
        engine.dispose()


def test_admin_cli_add_remove_and_errors_do_not_echo_identity_or_database(
    tmp_path, monkeypatch, capsys
):
    url = "sqlite:///" + str(tmp_path / "admin.db")
    monkeypatch.setenv("PROTOHUB_DATABASE_URL", url)
    factory = create_session_factory(url)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    try:
        assert main(["add", EMAIL, "--subject", SUBJECT]) == 0
        repo = SessionRepository(factory)
        assert repo.login_google(EMAIL, SUBJECT, False).email == EMAIL
        assert main(["add", EMAIL, "--subject", "different"]) == 2
        assert main(["remove", EMAIL]) == 0
        with pytest.raises(AuthenticationRequired):
            repo.login_google(EMAIL, SUBJECT, False)
        captured = capsys.readouterr()
        text = captured.out + captured.err
        assert EMAIL not in text and SUBJECT not in text and url not in text
    finally:
        engine.dispose()
