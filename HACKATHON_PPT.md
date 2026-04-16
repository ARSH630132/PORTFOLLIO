# Hackathon PPT Content: PS-A05 - Career Path Recommender for Tier 2/3 Students

**Track:** AI / ML Integration
**Theme:** Professional, tech-focused dark theme (Deep Green/Dark Blue)
**Fonts:** Clean Sans-serif (e.g., Inter, Roboto, or Montserrat)

---

## Slide 1: Title & Team
**Content:**
- **Main Title:** PS-A05: Career Path Recommender for Tier 2/3 Students
- **Sub-track:** Track: AI / ML Integration
- **Team Name:** [Insert Team Name]
- **Team Members:** [Member 1], [Member 2], [Member 3]

**Design Suggestions:**
- **Visual:** A high-impact hero image featuring a glowing digital roadmap or a student interacting with a holographic interface.
- **Layout:** Centered title with a semi-transparent dark overlay to ensure readability. Tech logos (OLA Krutrim, TrainX) in the corners.

---

## Slide 2: Problem Statement & Context
**Content:**
- **The Career Guidance Gap:** Tier 2/3 students lack access to professional career counsellors.
- **The Pain Point:** Decisions are often based on limited, biased, or outdated information from immediate circles.
- **Impact:** Mismatched careers, wasted potential, and high attrition in early jobs.
- **Goal:** Democratize access to realistic, data-backed career guidance for every student.

**Design Suggestions:**
- **Visual:** "Before vs. After" infographic.
    - *Before:* A student looking confused in a complex maze representing traditional guidance.
    - *After:* A clear, neon-lit digital path leading towards a bright horizon.
- **Icons:** Warning signs for "Bias" and "Limited Info"; a "Globe" icon for Democratization.

---

## Slide 3: Our Solution: "The AI Career Sherpa"
**Content:**
- **Concept:** An intelligent, interactive web application that acts as a personal mentor.
- **How it works:** Conducts a conversational "interview" to capture:
    - Interests & Passions
    - Current Skills & Academic Background
    - Socio-economic & Geographical Constraints
- **Value Prop:** Returns 3-5 personalized career roadmaps with learning resources and real-time market context.

**Design Suggestions:**
- **Visual:** A sleek screenshot mockup of the interactive chat/interview UI.
- **Icons:** Modern chat bubbles, a "Sherpa" or "Guide" icon, and document/roadmap icons.
- **Color Palette:** Dark blue background with neon green accents for interactive elements.

---

## Slide 4: System Architecture & Tech Stack
**Content:**
- **Data Flow:**
    1. **User Input:** Interactive Profile (Streamlit/FastAPI)
    2. **Data Processing:** Constraint Encoding (Python)
    3. **Matching Engine:** LangChain + Llama 3 (via Groq/TogetherAI)
    4. **Knowledge Base:** Simulated Naukri/LinkedIn dataset & Scraping scripts
    5. **Structured Output:** Personalized roadmaps + Salary data
- **Tech Stack:**
    - **Frontend:** Streamlit / React
    - **Backend:** Python (FastAPI)
    - **AI/ML:** LangChain, Llama 3, Scikit-learn
    - **Data:** Public APIs, Web Scraping

**Design Suggestions:**
- **Visual:** A clean, numbered flow diagram. Use standard tech logos for each component (Python, LangChain, Llama 3, etc.).
- **Style:** Dark mode diagram with glowing connecting lines.

---

## Slide 5: Methodology & Data Processing
**Content:**
- **User Profiling:** Utilizing Weighted Scoring for quantitative skills and LLM Reasoning for qualitative interests.
- **Data Strategy:**
    - *Hackathon Phase:* Simulated scraping and curated datasets from Naukri/LinkedIn.
    - *Production:* Integration with official job board APIs and government employment data.
- **Matching Logic:** Vectorized similarity search to match student profiles with successful career archetypes.
- **Scalability:** Plan to migrate from free LLM APIs to self-hosted Open Source models (Mistral/Llama) for data privacy.

**Design Suggestions:**
- **Visual:** A conceptual diagram of the matching engine (e.g., a "Black Box" taking inputs and projecting them into a vector space).
- **Icons:** Database (PostgreSQL/Pinecone), Brain (LLM), and Gear (Processing).

---

## Slide 6: Sample Output Mockup (The Roadmap)
**Content:**
- **Persona:** Arsh Singh, Tier 2 College Student.
- **Recommended Path:** Frontend Developer.
- **Roadmap:**
    - **0-6 Months:** Master HTML/CSS/JS (FreeCodeCamp, MDN).
    - **6-12 Months:** React Ecosystem & Portfolio projects (Junior Internships).
    - **1-2 Years:** Backend Basics (Node.js) & Full-stack transition.
- **Market Data:** Starting Salary: ₹4L - ₹8L (Based on local Tier 2 context).

**Design Suggestions:**
- **Visual:** A Gantt-style horizontal timeline or a branched tree roadmap.
- **Indicators:** Progress bars and milestone icons (Checkmarks, Trophies).

---

## Slide 7: Key Differentiators & Scalability Plan
**Content:**
- **Differentiators:**
    - **Local Context:** Factors in regional job availability and salary variations.
    - **Constraint-Aware:** Recommends paths based on the student's ability to afford further education or relocation.
- **Scalability:**
    - Integration with Pinecone for ultra-fast vector search.
    - Real-time job listing integration via LinkedIn/Indeed APIs.
- **Monetization:** Freemium model for students; Lead generation fees from ed-tech partners and recruiters.

**Design Suggestions:**
- **Visual:** A Radar Chart or Bar Chart comparing "AI Career Sherpa" vs "Traditional Career Counselling" across metrics like Cost, Accuracy, and Accessibility.

---

## Slide 8: Team & Next Steps (Q&A)
**Content:**
- **The Team:**
    - **[Name]:** ML Lead (AI Logic & LangChain)
    - **[Name]:** Full Stack Dev (Streamlit & API Integration)
    - **[Name]:** UX Lead (Design & Persona Research)
- **Next Steps:** Finalize the UI, enhance the scraping logic, and expand the learning resource database.
- **Acknowledgments:** Thank you OLA Krutrim & TrainX.
- **Call to Action:** Open for Q&A.

**Design Suggestions:**
- **Visual:** Clean layout with team avatars or professional photos.
- **Footer:** Contact info (GitHub, LinkedIn) and a "Thank You" message in a bold, italicized font.
