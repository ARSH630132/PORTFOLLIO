export interface Project {
  id: number;
  title: string;
  description: string;
  longDescription: string;
  techStack: string[];
  githubUrl: string;
  liveUrl: string;
  imageUrl: string;
  position: [number, number, number];
}

export interface Experience {
  id: number;
  company: string;
  role: string;
  period: string;
  description: string[];
  position: [number, number, number];
}

export interface Tech {
  name: string;
  icon?: string;
}

export const projects: Project[] = [
  {
    id: 1,
    title: "Quantum Flux",
    description: "A high-performance data visualization engine.",
    longDescription: "Quantum Flux uses WebGL to render millions of data points in real-time, providing deep insights into complex datasets with zero latency.",
    techStack: ["React", "Three.js", "TypeScript", "WebWorkers"],
    githubUrl: "https://github.com",
    liveUrl: "https://example.com",
    imageUrl: "https://picsum.photos/800/600?random=1",
    position: [-4, 0, 0],
  },
  {
    id: 2,
    title: "Nebula OS",
    description: "Cloud-native operating system interface.",
    longDescription: "A conceptual web-based OS that integrates seamlessly with cloud providers, offering a unified workspace for developers.",
    techStack: ["React", "Tailwind CSS", "Node.js", "Docker"],
    githubUrl: "https://github.com",
    liveUrl: "https://example.com",
    imageUrl: "https://picsum.photos/800/600?random=2",
    position: [0, 0, 0],
  },
  {
    id: 3,
    title: "Aether Link",
    description: "Decentralized communication protocol.",
    longDescription: "A peer-to-peer encrypted messaging system built on blockchain technology to ensure absolute privacy and security.",
    techStack: ["Rust", "WebAssembly", "React", "Solidity"],
    githubUrl: "https://github.com",
    liveUrl: "https://example.com",
    imageUrl: "https://picsum.photos/800/600?random=3",
    position: [4, 0, 0],
  },
  {
    id: 4,
    title: "AI Career Sherpa",
    description: "AI-driven career path recommender for students.",
    longDescription: "An intelligent platform that uses LLMs and real-market data to provide personalized career roadmaps and resources for Tier 2/3 city students.",
    techStack: ["Python", "LangChain", "Llama 3", "FastAPI", "Streamlit"],
    githubUrl: "https://github.com",
    liveUrl: "https://example.com",
    imageUrl: "https://picsum.photos/800/600?random=4",
    position: [8, 0, 0],
  },
];

export const experiences: Experience[] = [
  {
    id: 1,
    company: "Tech Nova",
    role: "Senior Frontend Engineer",
    period: "2022 - Present",
    description: [
      "Led the migration of the core dashboard to React 18, improving performance by 40%.",
      "Architected a reusable 3D component library using R3F.",
      "Mentored junior developers and established CI/CD best practices.",
    ],
    position: [0, 0, 0],
  },
  {
    id: 2,
    company: "Cyber Sphere",
    role: "Full Stack Developer",
    period: "2020 - 2022",
    description: [
      "Developed high-traffic e-commerce solutions using Next.js and GraphQL.",
      "Optimized database queries in PostgreSQL, reducing load times by 50%.",
      "Implemented automated E2E testing using Playwright.",
    ],
    position: [0, -5, 5],
  },
  {
    id: 3,
    company: "Digital Horizon",
    role: "Junior Web Developer",
    period: "2018 - 2020",
    description: [
      "Built responsive landing pages for various clients using HTML/CSS and JavaScript.",
      "Assisted in the development of a custom CMS internal tool.",
      "Maintained and updated legacy codebases.",
    ],
    position: [0, -10, 10],
  },
];

export const techStack: Tech[] = [
  { name: "React" },
  { name: "Three.js" },
  { name: "TypeScript" },
  { name: "Node.js" },
  { name: "Python" },
  { name: "Azure" },
  { name: "Tailwind" },
  { name: "Docker" },
  { name: "LangChain" },
  { name: "FastAPI" },
];

export const sectionCoordinates = {
  hero: [0, 0, 0],
  about: [0, -20, 20],
  projects: [0, -40, 40],
  timeline: [0, -60, 60],
  contact: [0, -80, 80],
};
