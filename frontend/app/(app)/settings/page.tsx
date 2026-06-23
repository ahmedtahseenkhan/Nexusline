"use client";

import ModulePlaceholder from "@/components/ModulePlaceholder";
import { IconSettings } from "@/components/icons";

export default function SettingsPage() {
  return (
    <ModulePlaceholder
      title="Settings"
      description="Organization configuration, integrations and automation."
      icon={<IconSettings width={24} height={24} />}
      planned={[
        "Organization profile and branding",
        "Risk scoring matrix and appetite/tolerance thresholds",
        "Notification rules and email templates",
        "REST API keys, webhooks and integrations",
        "SSO / SAML / OAuth identity configuration",
      ]}
    />
  );
}
