import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ImageAttachments } from "./ImageAttachments";
import type { ImageInfo } from "../../types/image";

const shot: ImageInfo = { id: "i1", filename: "menu.png", media_type: "image/png", size_bytes: 10, width: 3, height: 2, created_by: "human", created_at: "2026-10-20T00:00:00Z" };
const posts: { url: string; type: string | null }[] = [];

function show(images: ImageInfo[] = [], readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ImageAttachments projectId="p1" owner="tasks" record="CAMP-001" images={images} readOnly={readOnly} /></QueryClientProvider>);
}

const png = (name = "shot.png") => new File([new Uint8Array([137, 80, 78, 71])], name, { type: "image/png" });

beforeEach(() => {
  posts.length = 0;
  URL.createObjectURL = vi.fn(() => "blob:shot");
  URL.revokeObjectURL = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input);
    if (options?.method === "POST") {
      posts.push({ url, type: new Headers(options.headers).get("Content-Type") });
      return Response.json({ ...shot, id: `i${posts.length + 1}` }, { status: 201 });
    }
    if (options?.method === "DELETE") return new Response(null, { status: 204 });
    return new Response(new Blob(["x"], { type: "image/png" }));
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("ImageAttachments", () => {
  it("attaches images by browsing, dropping, and pasting", async () => {
    show();
    await userEvent.upload(screen.getByLabelText("Choose images"), png("browsed.png"));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ url: "/api/projects/p1/tasks/CAMP-001/images?filename=browsed.png", type: "image/png" });

    fireEvent.drop(screen.getByText(/Drop images here/), { dataTransfer: { files: [png("dropped.png")] } });
    await waitFor(() => expect(posts).toHaveLength(2));

    const paste = new Event("paste", { bubbles: true }) as Event & { clipboardData: unknown };
    paste.clipboardData = { files: [new File([new Uint8Array([1])], "", { type: "image/png" })] };
    document.dispatchEvent(paste);
    await waitFor(() => expect(posts).toHaveLength(3));
    expect(posts[2].url).toContain("filename=pasted%20image");
  });

  it("refuses files that are not images before sending them", async () => {
    show();
    fireEvent.drop(screen.getByText(/Drop images here/), { dataTransfer: { files: [new File(["hi"], "notes.txt", { type: "text/plain" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("notes.txt is not a PNG, JPEG, WebP or GIF image.");
    expect(posts).toHaveLength(0);
  });

  it("shows, opens and removes attached images, and hides editing when read only", async () => {
    const { unmount } = show([shot]);
    await userEvent.click(screen.getByRole("button", { name: "View menu.png" }));
    expect(await screen.findByRole("img", { name: "menu.png" })).toHaveAttribute("src", "blob:shot");
    await userEvent.click(screen.getByRole("button", { name: "Close image" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove menu.png" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove image" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/projects/p1/images/i1", expect.objectContaining({ method: "DELETE" })));
    unmount();

    show([shot], true);
    expect(screen.queryByRole("button", { name: "Remove menu.png" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Drop images here/)).not.toBeInTheDocument();
  });
});
