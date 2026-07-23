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
  published_at: z.string().nullish().transform(v => v ?? null),
  score: z.number().nullish().transform(v => v ?? null),
  tags_json: z.string().nullish().transform(v => v ?? '[]'),
  summary_bullets_json: z.string().nullish().transform(v => v ?? '[]'),
  reason: z.string().nullish().transform(v => v ?? null),
  read_at: z.string().nullish().transform(v => v ?? null),
  bookmarked: z.boolean(),
  extraction_failed: z.boolean(),
  created_at: z.string(),
  feed_name: z.string().nullish().transform(v => v ?? ''),
  user_feedback: z.number().nullish().transform(v => v ?? null),
  contribution_type: ContribTypeSchema.nullish().transform(v => v ?? null),
  re_document_type: REDocTypeSchema.nullish().transform(v => v ?? null),
  threat_overlap: z.number().nullish(),
  threat_positioning_note: z.string().nullish(),
  tracked_author_alert: z.boolean().nullish(),
  cited_by_corpus_count: z.number().optional(),
  tags: z.array(z.string()).nullish().transform(v => v ?? []),
  summary_bullets: z.array(z.string()).nullish().transform(v => v ?? [])
})

// Detailed Article schema
export const ArticleSchema = z.object({
  id: z.number(),
  feed_id: z.number(),
  title: z.string(),
  url: z.string(),
  published_at: z.string().nullish().transform(v => v ?? null),
  author: z.string().nullish().transform(v => v ?? null),
  content_html: z.string().nullish().transform(v => v ?? null),
  content_text: z.string().nullish().transform(v => v ?? null),
  images_json: z.string().nullish().transform(v => v ?? '[]'),
  score: z.number().nullish().transform(v => v ?? null),
  tags_json: z.string().nullish().transform(v => v ?? '[]'),
  summary_bullets_json: z.string().nullish().transform(v => v ?? '[]'),
  reason: z.string().nullish().transform(v => v ?? null),
  read_at: z.string().nullish().transform(v => v ?? null),
  bookmarked: z.boolean(),
  extraction_failed: z.boolean(),
  created_at: z.string(),
  user_feedback: z.number().nullish().transform(v => v ?? null),
  contribution_type: ContribTypeSchema.nullish().transform(v => v ?? null),
  re_document_type: REDocTypeSchema.nullish().transform(v => v ?? null),
  paper_meta: z.any().nullish().transform(v => v ?? {}),
  score_meta: z.any().nullish().transform(v => v ?? {}),
  embedding_indexed: z.number().nullish().transform(v => v ?? null),
  tags: z.array(z.string()).nullish().transform(v => v ?? []),
  summary_bullets: z.array(z.string()).nullish().transform(v => v ?? []),
  images: z.array(z.string()).nullish().transform(v => v ?? [])
})

// Schema for paginated/list responses if they are wrapped, but the backend currently returns an array directly:
export const ArticleListResponseSchema = z.array(ArticleListItemSchema)
