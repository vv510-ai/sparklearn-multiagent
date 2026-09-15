import { redirect } from "next/navigation";

// Keep old bookmarks useful after retiring the project-materials page.
export default function EvidencePage() {
  redirect("/");
}
