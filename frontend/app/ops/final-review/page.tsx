import type { Metadata } from "next";
import FinalReviewOperatorPage from "@/components/demo/FinalReviewOperatorPage";

export const metadata: Metadata = {
  title: "演示操作台 · 知行循证",
  robots: { index: false, follow: false },
};

export default function OperatorPage() {
  return <FinalReviewOperatorPage />;
}
