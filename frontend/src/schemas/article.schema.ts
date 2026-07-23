import { z } from 'zod'

// We match the ContribType and REDocType from types.ts
export const ContribTypeSchema = z.union([
  z.literal('method'), z.literal('benchmark'), z.literal('survey'), z.literal('empirical'),
  z.literal('theory'), z.literal('position'), z.literal('tool'), z.literal('incident'),
  z.literal('tutorial'), z.literal('news'), z.literal('other')
])

export const REDocTypeSchema = z.union([
  z.literal('elicitation'), z.literal('extraction'), z.literal('method'), z.literal('none')
])

export const ArticleListItemSchema = z.object({
  id: z.number(),
  feed_id: z.number(),
  title: z.string(),
  url: z.string(),
  published_at: z.string().nullable().optional(),
  score: z.number().nullable().optional(),
  tags_json: z.string().optional(),
  summary_bullets_json: z.string().optional(),
  reason: z.string().nullable().optional(),
  read_at: z.string().nullable().optional(),
  bookmarked: z.boolean(),
  extraction_failed: z.boolean(),
  created_at: z.string(),
  feed_name: z.string().optional(),
  user_feedback: z.number().nullable().optional(),
  contribution_type: ContribTypeSchema.nullable().optional(),
  re_document_type: REDocTypeSchema.nullable().optional(),
  threat_overlap: z.number().nullable().optional(),
  threat_positioning_note: z.string().nullable().optional(),
  tracked_author_alert: z.boolean().nullable().optional(),
  cited_by_corpus_count: z.number().optional(),
  tags: z.array(z.string()).optional(),
  summary_bullets: z.array(z.string()).optional()
})

// Detailed Article schema
export const ArticleSchema = z.object({
  id: z.number(),
  feed_id: z.number(),
  title: z.string(),
  url: z.string(),
  published_at: z.string().nullable().optional(),
  author: z.string().nullable().optional(),
  content_html: z.string().nullable().optional(),
  content_text: z.string().nullable().optional(),
  images_json: z.string().optional(),
  score: z.number().nullable().optional(),
  tags_json: z.string().optional(),
  summary_bullets_json: z.string().optional(),
  reason: z.string().nullable().optional(),
  read_at: z.string().nullable().optional(),
  bookmarked: z.boolean(),
  extraction_failed: z.boolean(),
  created_at: z.string(),
  user_feedback: z.number().nullable().optional(),
  contribution_type: ContribTypeSchema.nullable().optional(),
  re_document_type: REDocTypeSchema.nullable().optional(),
  paper_meta: z.any().optional(),
  score_meta: z.any().optional(),
  embedding_indexed: z.number().nullable().optional(),
  tags: z.array(z.string()).optional(),
  summary_bullets: z.array(z.string()).optional(),
  images: z.array(z.string()).optional()
})

// Schema for paginated/list responses if they are wrapped, but the backend currently returns an array directly:
export const ArticleListResponseSchema = z.array(ArticleListItemSchema)
