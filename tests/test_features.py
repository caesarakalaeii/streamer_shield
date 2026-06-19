from datetime import datetime, timedelta, timezone

import features


def test_clean_username_lowercases_and_strips_specials():
    assert features.clean_username("Foo-Bar") == "foo bar"
    assert features.clean_username("Keep_Underscore1") == "keep_underscore1"


def test_numeric_vector_length_matches_contract():
    inp = features.build_model_inputs(login="someuser")
    assert len(inp["numeric"]) == features.NUM_NUMERIC_FEATURES == 12
    assert set(inp.keys()) == {"username", "bio", "numeric"}


def test_missing_follower_count_sets_known_flag_zero():
    inp = features.build_model_inputs(login="u", follower_count=None)
    idx_log = features.NUMERIC_FEATURE_NAMES.index("follower_count_log")
    idx_known = features.NUMERIC_FEATURE_NAMES.index("follower_known")
    assert inp["numeric"][idx_log] == 0.0
    assert inp["numeric"][idx_known] == 0.0


def test_present_follower_count_is_log_scaled():
    inp = features.build_model_inputs(login="u", follower_count=99)
    idx_log = features.NUMERIC_FEATURE_NAMES.index("follower_count_log")
    idx_known = features.NUMERIC_FEATURE_NAMES.index("follower_known")
    assert abs(inp["numeric"][idx_log] - __import__("math").log1p(99)) < 1e-9
    assert inp["numeric"][idx_known] == 1.0


def test_follow_age_is_minus_one_when_not_following():
    inp = features.build_model_inputs(login="u", follows_channel=False, follow_age_days=10)
    idx = features.NUMERIC_FEATURE_NAMES.index("follow_age_days")
    assert inp["numeric"][idx] == -1.0


def test_broadcaster_type_one_hot():
    aff = features.build_model_inputs(login="u", broadcaster_type="affiliate")["numeric"]
    par = features.build_model_inputs(login="u", broadcaster_type="partner")["numeric"]
    none = features.build_model_inputs(login="u", broadcaster_type="")["numeric"]
    ia = features.NUMERIC_FEATURE_NAMES.index("broadcaster_affiliate")
    ip = features.NUMERIC_FEATURE_NAMES.index("broadcaster_partner")
    assert (aff[ia], aff[ip]) == (1.0, 0.0)
    assert (par[ia], par[ip]) == (0.0, 1.0)
    assert (none[ia], none[ip]) == (0.0, 0.0)


def test_bio_signal_detectors():
    assert features.bio_has_url("check my discord.gg/abc")
    assert features.bio_has_url("https://t.me/scam")
    assert not features.bio_has_url("just a normal streamer bio")
    assert features.bio_has_scam_keyword("FREE gift card giveaway!!")
    assert not features.bio_has_scam_keyword("i play souls games")


def test_has_default_avatar():
    assert features.has_default_avatar(
        "https://static-cdn.jtvnw.net/user-default-pictures-uv/abc.png"
    )
    assert not features.has_default_avatar(
        "https://static-cdn.jtvnw.net/jtv_user_pictures/real-avatar.png"
    )


def test_account_age_days():
    created = datetime.now(timezone.utc) - timedelta(days=365)
    age = features.account_age_days(created)
    assert 364 <= age <= 366
    assert features.account_age_days(None) == 0.0
