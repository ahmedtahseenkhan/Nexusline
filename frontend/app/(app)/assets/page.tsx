"use client";

// The single "Asset Management" module was split (ISO 27005 primary/supporting) into
// IT Asset Management and Information Asset Management. This legacy route now redirects.
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AssetsRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/it-assets");
  }, [router]);
  return (
    <div className="empty" style={{ padding: 48 }}>
      <h3>Asset Management has moved</h3>
      <p>
        This module was split into <a href="/it-assets">IT Asset Management</a> and{" "}
        <a href="/information-assets">Information Assets</a>. Redirecting…
      </p>
    </div>
  );
}
