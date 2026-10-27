import type { Metadata } from "next";
import ForgotPasswordForm from "@/components/ForgotPasswordForm";
import { NOINDEX } from "@/lib/seo";

export const metadata: Metadata = { title: "Reset your password", ...NOINDEX };

export default function ForgotPasswordPage() {
  return <ForgotPasswordForm />;
}
