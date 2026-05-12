import json
from fetch_linkedin_profile import parse_profile_data

def test_full_data():
    sample_data = {
        "firstName": "John",
        "lastName": "Doe",
        "headline": "Senior Software Engineer",
        "summary": "Experienced developer with a passion for AI.",
        "experience": [
            {
                "companyName": "Tech Corp",
                "title": "Lead Dev",
                "timePeriod": {
                    "startDate": {"month": 1, "year": 2020},
                    "endDate": {"month": 12, "year": 2023}
                }
            },
            {
                "companyName": "Startup Inc",
                "title": "Junior Dev",
                "duration": "2 years"
            }
        ],
        "education": [
            {
                "schoolName": "University of Tech",
                "degreeName": "Bachelor of Science",
                "fieldOfStudy": "Computer Science"
            }
        ]
    }

    parsed = parse_profile_data(sample_data)
    print(json.dumps(parsed, indent=2))

    assert parsed["full_name"] == "John Doe"
    assert parsed["headline"] == "Senior Software Engineer"
    assert parsed["about_summary"] == "Experienced developer with a passion for AI."
    assert len(parsed["work_experience"]) == 2
    assert parsed["work_experience"][0]["company"] == "Tech Corp"
    assert parsed["work_experience"][0]["duration"] == "1/2020 - 12/2023"
    assert parsed["work_experience"][1]["duration"] == "2 years"
    assert parsed["education"][0]["school"] == "University of Tech"
    print("test_full_data passed!")

def test_missing_fields():
    sample_data = {
        "fullName": "Jane Smith",
        "headline": None,
        "experience": [
            {
                "companyName": "Consulting LLC",
                # missing title
            }
        ]
        # missing summary, education
    }

    parsed = parse_profile_data(sample_data)
    print(json.dumps(parsed, indent=2))

    assert parsed["full_name"] == "Jane Smith"
    assert parsed["headline"] == "N/A"
    assert parsed["about_summary"] == "N/A"
    assert len(parsed["work_experience"]) == 1
    assert parsed["work_experience"][0]["title"] == "N/A"
    assert parsed["work_experience"][0]["duration"] == "N/A"
    assert parsed["education"] == []
    print("test_missing_fields passed!")

def test_empty_data():
    parsed = parse_profile_data({})
    assert parsed == {}

    parsed = parse_profile_data(None)
    assert parsed == {}
    print("test_empty_data passed!")

if __name__ == "__main__":
    test_full_data()
    test_missing_fields()
    test_empty_data()
    print("\nAll parsing tests passed successfully!")
