"""Regression tests for ACTIVE-job vacancy authority."""

from __future__ import annotations

from types import SimpleNamespace

from app.graph.vacancy import (
    NO_ACTIVE_JOB_REPLY,
    VACANCY_LOOKUP_UNAVAILABLE_REPLY,
    format_vacancy_lookup,
    is_explicit_vacancy_question,
    vacancy_lookup_query,
)
from app.services.recommendation.availability import ActiveJob, ActiveJobLookup, select_matching_active_jobs


REPORTED_LG_QUERY = (
    "mình nhà ở quoán toan _hp gần lG tràng duệ."
    "bên lG tràng duệ mình đang tuyển ạ"
)


def _job(**overrides) -> ActiveJob:
    values = {
        "id": "job-1",
        "title": "Thợ hàn CO2",
        "company_name": "VFIC Manufacturing",
        "factory_name": "Nhà máy A",
        "province": "Hải Phòng",
        "salary_min": 10_000_000,
        "salary_max": 14_000_000,
        "vacancy_count": 1,
    }
    values.update(overrides)
    return ActiveJob(**values)


def test_explicit_co2_welder_question_is_a_vacancy_lookup():
    assert is_explicit_vacancy_question("bên bạn tuyển thợ hàn Co2 đúng ko?")
    assert is_explicit_vacancy_question("có tuyển thợ hàn CO2 không?")
    assert is_explicit_vacancy_question("hiện còn tuyển thợ hàn CO2 không?")
    assert is_explicit_vacancy_question("bên bạn tuyển thợ hàn CO2?")
    assert is_explicit_vacancy_question("thợ hàn CO2 còn không?")
    assert is_explicit_vacancy_question("bên bạn có nhận thợ hàn không?")
    assert is_explicit_vacancy_question("còn lao động phổ thông không")
    assert is_explicit_vacancy_question("còn lái xe không")
    assert is_explicit_vacancy_question("còn công nhân không")
    assert is_explicit_vacancy_question("bên bạn nhận công nhân không?")
    assert not is_explicit_vacancy_question("tôi muốn ứng tuyển thợ hàn CO2")


def test_messaging_complaint_is_not_a_vacancy_lookup():
    # Accent collision: de-accenting turns "nhắn tin" (send a message) into the
    # same token as "nhận" (accept workers), which previously misread a slow-reply
    # complaint as a hiring question and answered it with NO_ACTIVE_JOB_REPLY.
    complaint = (
        "Khi tôi cần và nhắn tin cho shop thì lại mất 1 ngày shop mới hồi âm "
        "thì tôi cũng không chờ được"
    )
    assert not is_explicit_vacancy_question(complaint)
    assert vacancy_lookup_query(complaint, []) is None
    # Other phrasings about messaging must also fall through to the agent.
    assert not is_explicit_vacancy_question("shop nhắn tin lại quá chậm")
    assert not is_explicit_vacancy_question("tôi nhắn tin mà không ai trả lời")
    # The legitimate "nhận" (accept workers) path is unaffected.
    assert is_explicit_vacancy_question("bên bạn có nhận thợ hàn không?")


def test_exact_role_match_returns_same_active_job_evidence():
    job = _job()
    outcome = select_matching_active_jobs("bên bạn tuyển thợ hàn Co2 đúng ko?", [job])

    assert outcome.status == "matched"
    assert outcome.jobs == (job,)
    rendered = format_vacancy_lookup(outcome)
    assert "Thợ hàn CO2" in rendered
    assert "VFIC Manufacturing" in rendered
    assert "10-14 triệu" in rendered


def test_candidate_home_context_does_not_block_company_vacancy_lookup():
    job = _job(
        title="Công nhân sản xuất",
        company_name="LG Display",
        factory_name="LG Display Tràng Duệ",
        province="Hải Phòng",
    )

    focused_query = vacancy_lookup_query(REPORTED_LG_QUERY, [])
    outcome = select_matching_active_jobs(focused_query or "", [job])

    assert focused_query == "bên lG tràng duệ mình đang tuyển ạ"
    assert outcome.status == "matched"
    assert outcome.jobs == (job,)

    no_punctuation = REPORTED_LG_QUERY.replace(".", " ")
    assert vacancy_lookup_query(no_punctuation, []) == "bên lG tràng duệ mình đang tuyển ạ"


def test_two_character_company_alias_is_not_discarded():
    lg_job = _job(
        title="Công nhân sản xuất",
        company_name="Công ty TNHH Điện tử",
        company_aliases=("LG", "LGD"),
    )
    unrelated_job = _job(
        id="job-2",
        title="Công nhân sản xuất",
        company_name="Samsung Display",
    )

    outcome = select_matching_active_jobs("LG đang tuyển ạ", [unrelated_job, lg_job])

    assert outcome.status == "matched"
    assert outcome.jobs == (lg_job,)


def test_company_typo_and_conversational_words_still_resolve_verified_job():
    lg_job = _job(
        title="Công nhân sản xuất",
        company_name="LG Display",
        company_aliases=("LG",),
    )

    outcome = select_matching_active_jobs(
        "mình thấy LG dislay bạn viết là đang tuyển mà",
        [lg_job],
    )

    assert outcome.status == "matched"
    assert outcome.jobs == (lg_job,)


def test_company_match_does_not_authorize_an_unmatched_role():
    lg_operator = _job(title="Công nhân sản xuất", company_name="LG Display")

    outcome = select_matching_active_jobs("LG tuyển thợ hàn không?", [lg_operator])

    assert outcome.status == "no_match"


def test_empty_structured_catalog_is_not_a_negative_hiring_claim():
    outcome = select_matching_active_jobs("LG Tràng Duệ đang tuyển ạ", [])

    assert outcome.status == "catalog_empty"
    assert outcome.jobs == ()


def test_single_matched_job_renders_verified_advisory_details():
    job = _job(
        title="Công nhân thời vụ",
        company_name="LG Display",
        factory_name="Khu công nghiệp Tràng Duệ",
        district="An Dương",
        province="Hải Phòng",
        age_min=18,
        age_max=50,
        gender_requirement="Nam/Nữ",
        experience_required="Không yêu cầu kinh nghiệm, có đào tạo",
        shift="Ca ngày hoặc ca đêm",
        transport_support=True,
        accommodation_support=True,
        description="Sản xuất và kiểm tra màn hình.",
        requirements="Hồ sơ gồm CCCD.",
    )

    rendered = format_vacancy_lookup(ActiveJobLookup("matched", (job,)))

    assert "Đúng rồi ạ" in rendered
    assert "LG Display" in rendered
    assert "Khu công nghiệp Tràng Duệ, An Dương, Hải Phòng" in rendered
    assert "Công nhân thời vụ" in rendered
    assert "18–50 tuổi" in rendered
    assert "Nam/Nữ" in rendered
    assert "Không yêu cầu kinh nghiệm, có đào tạo" in rendered
    assert "Hồ sơ gồm CCCD" in rendered
    assert "xe đưa đón" in rendered
    assert "chỗ ở" in rendered


def test_single_matched_job_does_not_invent_missing_requirements():
    rendered = format_vacancy_lookup(
        ActiveJobLookup(
            "matched",
            (
                _job(
                    title="Công nhân sản xuất",
                    company_name="LG Display",
                    requirements="",
                    experience_required="",
                ),
            ),
        )
    )

    assert "CCCD" not in rendered
    assert "không yêu cầu kinh nghiệm" not in rendered.lower()


def test_nonmatching_catalog_like_words_do_not_match_welder_query():
    unrelated = _job(
        title="Lao động phổ thông",
        company_name="LG Display Vietnam",
        factory_name="Nhân viên sản xuất",
    )
    outcome = select_matching_active_jobs("bên bạn tuyển thợ hàn CO2 đúng ko?", [unrelated])

    assert outcome.status == "no_match"
    assert format_vacancy_lookup(outcome) == NO_ACTIVE_JOB_REPLY


def test_unavailable_lookup_never_claims_no_vacancy():
    reply = format_vacancy_lookup(ActiveJobLookup("unavailable"))

    assert reply == VACANCY_LOOKUP_UNAVAILABLE_REPLY
    assert "chưa tuyển" not in reply.lower()


def test_salary_followup_reuses_recent_candidate_vacancy_question():
    history = [
        SimpleNamespace(sender="WORKER", body="bên bạn tuyển thợ hàn Co2 đúng ko?"),
        SimpleNamespace(sender="BOT", body=NO_ACTIVE_JOB_REPLY),
    ]

    assert vacancy_lookup_query("lương bao nhiêu?", history) == history[0].body
    assert vacancy_lookup_query("ở đâu vậy?", history) == history[0].body
    assert vacancy_lookup_query("làm ca nào?", history) == history[0].body
    assert vacancy_lookup_query("cần kinh nghiệm không?", history) == history[0].body


def test_salary_followup_does_not_revive_an_older_vacancy_topic():
    history = [
        SimpleNamespace(sender="WORKER", body="bên bạn tuyển thợ hàn CO2 đúng ko?"),
        SimpleNamespace(sender="BOT", body=NO_ACTIVE_JOB_REPLY),
        SimpleNamespace(sender="WORKER", body="tôi muốn hỏi về lịch xe"),
    ]

    assert vacancy_lookup_query("lương bao nhiêu?", history) is None


def test_generic_vacancy_followup_reuses_the_immediately_prior_role():
    history = [
        SimpleNamespace(sender="WORKER", body="bên bạn tuyển thợ hàn CO2 đúng ko?"),
        SimpleNamespace(sender="BOT", body="Có, VFIC hiện đang tuyển."),
    ]

    assert vacancy_lookup_query("công việc này còn không?", history) == history[0].body


def test_multiple_matches_keep_each_jobs_facts_on_its_own_line():
    first = _job(company_name="Công ty A", province="Hải Phòng", salary_min=10_000_000, salary_max=14_000_000)
    second = _job(
        id="job-2",
        title="Thợ hàn CO2 ca đêm",
        company_name="Công ty B",
        province="Bắc Ninh",
        salary_min=15_000_000,
        salary_max=18_000_000,
    )
    rendered = format_vacancy_lookup(ActiveJobLookup("matched", (first, second)))

    lines = rendered.splitlines()
    assert "Công ty A" in lines[1] and "10-14 triệu" in lines[1]
    assert "Công ty B" in lines[2] and "15-18 triệu" in lines[2]
    assert "Công ty B" not in lines[1]
