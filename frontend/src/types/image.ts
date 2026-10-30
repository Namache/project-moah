/** An image attached to a task or memory record. The picture itself is fetched separately. */
export interface ImageInfo {
  id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  created_by: string | null;
  created_at: string;
}

export type ImageOwner = "tasks" | "memory";

/** Matches the backend: Claude reads these four types, up to 5 MB each. */
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const MAX_IMAGES_PER_RECORD = 10;
