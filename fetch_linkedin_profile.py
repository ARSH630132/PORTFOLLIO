import requests
import json

# Configuration
RAPID_API_KEY = "YOUR_RAPID_API_KEY_HERE"
RAPID_API_HOST = "linkedin-data-api.p.rapidapi.com"
API_URL = "https://linkedin-data-api.p.rapidapi.com/get-profile-data-by-url"

def fetch_linkedin_profile(profile_url):
    """
    Fetches LinkedIn profile data using RapidAPI.
    """
    headers = {
        "x-rapidapi-key": RAPID_API_KEY,
        "x-rapidapi-host": RAPID_API_HOST
    }
    params = {"url": profile_url}

    try:
        response = requests.get(API_URL, headers=headers, params=params)

        # Handle specific error codes
        if response.status_code == 403:
            return {"error": "403 Forbidden: Subscription issues or invalid API key."}
        elif response.status_code == 404:
            return {"error": "404 Not Found: The profile URL might be incorrect or the profile is private."}
        elif response.status_code == 429:
            return {"error": "429 Too Many Requests: Rate limit exceeded."}

        response.raise_for_status()

        data = response.json()
        return parse_profile_data(data)

    except requests.exceptions.RequestException as e:
        return {"error": f"Request failed: {str(e)}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {str(e)}"}

def parse_profile_data(data):
    """
    Parses the raw API response into a clean JSON structure for LLM analysis.
    Handles None values gracefully.
    """
    if not data:
        return {}

    # Helper function to safely get values
    def get_safe(obj, key, default=None):
        return obj.get(key) if obj and isinstance(obj, dict) else default

    # Extracting Basic Info
    first_name = get_safe(data, 'firstName', '')
    last_name = get_safe(data, 'lastName', '')

    if first_name or last_name:
        full_name = f"{first_name or ''} {last_name or ''}".strip()
    else:
        full_name = get_safe(data, 'fullName', 'N/A')

    headline = get_safe(data, 'headline', 'N/A')
    summary = get_safe(data, 'summary', 'N/A')

    # Extracting Work Experience
    experience = []
    raw_experience = get_safe(data, 'experience', [])
    if isinstance(raw_experience, list):
        for exp in raw_experience:
            company = get_safe(exp, 'companyName', 'N/A')
            title = get_safe(exp, 'title', 'N/A')

            # Handling Duration
            # Some APIs provide 'timePeriod' object with 'startDate' and 'endDate'
            # Others might provide a 'duration' string.
            duration = get_safe(exp, 'duration')
            if not duration:
                time_period = get_safe(exp, 'timePeriod')
                if time_period:
                    start = get_safe(time_period, 'startDate')
                    end = get_safe(time_period, 'endDate', 'Present')

                    def format_date(d):
                        if not d: return ""
                        year = get_safe(d, 'year', '')
                        month = get_safe(d, 'month', '')
                        if month and year: return f"{month}/{year}"
                        return str(year)

                    start_str = format_date(start)
                    end_str = format_date(end) if isinstance(end, dict) else str(end)
                    if start_str:
                        duration = f"{start_str} - {end_str}"

            experience.append({
                "company": company or "N/A",
                "title": title or "N/A",
                "duration": duration or "N/A"
            })

    # Extracting Education
    education = []
    raw_education = get_safe(data, 'education', [])
    if isinstance(raw_education, list):
        for edu in raw_education:
            school = get_safe(edu, 'schoolName', 'N/A')
            degree = get_safe(edu, 'degreeName', 'N/A')
            field = get_safe(edu, 'fieldOfStudy', 'N/A')

            education.append({
                "school": school,
                "degree": degree,
                "field_of_study": field
            })

    # Final Formatted Object
    parsed_profile = {
        "full_name": full_name or "N/A",
        "headline": headline or "N/A",
        "about_summary": summary or "N/A",
        "work_experience": experience,
        "education": education
    }

    return parsed_profile

if __name__ == "__main__":
    # Example usage
    test_url = "https://www.linkedin.com/in/reidhoffman/"
    print(f"Fetching data for: {test_url}\n")

    profile_data = fetch_linkedin_profile(test_url)

    # Output as clean JSON
    print(json.dumps(profile_data, indent=2))
