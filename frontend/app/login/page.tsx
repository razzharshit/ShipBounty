import Image from "next/image";
import { GitPullRequest } from "lucide-react";
import { DemoLogin } from "@/components/auth/demo-login";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function LoginPage() {
  const demoEnabled = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#F8FAFC] px-6">
      <Card className="w-full max-w-md border-[#E2E8F0] bg-white shadow-sm">
        <CardHeader className="space-y-3 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center overflow-hidden rounded-xl border border-slate-200 bg-slate-900 shadow-md">
            <Image
              src="/shipbounty-logo.png"
              alt="ShipBounty Logo"
              width={56}
              height={56}
              className="h-full w-full object-cover"
            />
          </div>
          <CardTitle className="text-xl text-[#0F172A]">
            <h1>Sign in to ShipBounty</h1>
          </CardTitle>
          <p className="text-sm text-[#64748B]">
            Repository access is limited to the GitHub App installations and
            permissions available to your GitHub account.
          </p>
        </CardHeader>
        <CardContent>
          <a
            className={cn(buttonVariants(), "w-full")}
            href={`${API_URL}/auth/github/start`}
          >
            <GitPullRequest className="mr-2 h-4 w-4" />
            Continue with GitHub
          </a>
          {demoEnabled ? (
            <DemoLogin
              apiUrl={API_URL}
              defaultWorkspace={
                process.env.NEXT_PUBLIC_DEMO_WORKSPACE ?? ""
              }
            />
          ) : null}
        </CardContent>
      </Card>
    </main>
  );
}
