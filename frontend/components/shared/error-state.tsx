import { AlertCircle } from "lucide-react";

interface ErrorStateProps {
  title?: string;
  description: string;
}

export function ErrorState({
  title = "Something went wrong",
  description,
}: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-red-100">
        <AlertCircle className="h-5 w-5 text-red-600" />
      </div>
      <h3 className="text-base font-semibold text-[#0F172A]">{title}</h3>
      <p className="mt-1.5 max-w-md text-sm text-[#64748B]">{description}</p>
    </div>
  );
}
