import { t } from "../lib/i18n";
import type { ImageInfo, ImageOwner } from "../types/image";
import { ApiError, authHeaders, json, request } from "./client";

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;

export const imagesApi = {
  /** Sends the file itself as the body; the backend checks its bytes, not its name. */
  attach: (projectId: string, owner: ImageOwner, ref: string, file: Blob, filename: string) =>
    request<ImageInfo>(`${base(projectId)}/${owner}/${encodeURIComponent(ref)}/images?filename=${encodeURIComponent(filename)}`, {
      method: "POST",
      body: file,
      headers: { "Content-Type": file.type || "application/octet-stream" },
    }),
  remove: (projectId: string, imageId: string) => request<void>(`${base(projectId)}/images/${encodeURIComponent(imageId)}`, json("DELETE")),
  /** The picture as a blob: an <img> cannot send the desktop token, so it shows an object URL. */
  async blob(projectId: string, imageId: string, signal?: AbortSignal): Promise<Blob> {
    const response = await fetch(`/api${base(projectId)}/images/${encodeURIComponent(imageId)}`, { headers: authHeaders(), signal });
    if (!response.ok) throw new ApiError(t("The image could not be loaded."), response.status);
    return response.blob();
  },
};
