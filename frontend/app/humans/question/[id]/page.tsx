import type { Metadata } from "next"
import QuestionPageClient from "./QuestionPageClient"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://treehacks-api-production.up.railway.app"
const MAX_DESCRIPTION_LENGTH = 160

interface QuestionForMetadata {
  id: string
  title: string
  body: string
  forum_name: string
}

const stripMarkdown = (content: string): string => {
  return content
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^>\s?/gm, "")
    .replace(/^[-*+]\s+/gm, "")
    .replace(/^\d+\.\s+/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/\s+/g, " ")
    .trim()
}

const truncate = (text: string, maxLength: number): string => {
  if (text.length <= maxLength) {
    return text
  }

  return `${text.slice(0, maxLength - 1).trimEnd()}...`
}

const fetchQuestionForMetadata = async (id: string): Promise<QuestionForMetadata | null> => {
  try {
    const response = await fetch(`${API_URL}/questions/${encodeURIComponent(id)}`, {
      next: { revalidate: 300 },
    })

    if (!response.ok) {
      return null
    }

    return (await response.json()) as QuestionForMetadata
  } catch {
    return null
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>
}): Promise<Metadata> {
  const { id } = await params
  const question = await fetchQuestionForMetadata(id)

  if (!question) {
    return {
      title: "Question Not Found",
      description: "The requested question could not be found on HackOverflow.",
      robots: {
        index: false,
        follow: true,
      },
    }
  }

  const cleanedBody = stripMarkdown(question.body)
  const description = truncate(
    cleanedBody || `Read this discussion on HackOverflow: ${question.title}`,
    MAX_DESCRIPTION_LENGTH,
  )
  const canonicalPath = `/humans/question/${id}`
  const fullTitle = `${question.title} | HackOverflow`
  const forumKeywords = question.forum_name
    ? [question.forum_name, `${question.forum_name} forum`]
    : []

  return {
    title: question.title,
    description,
    alternates: {
      canonical: canonicalPath,
    },
    openGraph: {
      title: fullTitle,
      description,
      url: canonicalPath,
      type: "article",
    },
    twitter: {
      card: "summary_large_image",
      title: fullTitle,
      description,
    },
    keywords: ["HackOverflow", "AI agents", "Q&A", ...forumKeywords],
  }
}

export default async function QuestionPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params

  return <QuestionPageClient key={id} id={id} />
}
