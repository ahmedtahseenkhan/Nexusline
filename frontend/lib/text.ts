// Turning stored keys ("rcsa_assessment", "it_asset") into labels people read.
//
// Every page used to carry its own copy of a capitalise-each-word helper, which is how
// "Rcsa Assessment", "Bia", "Dsar" and "Icfr" reached the screen. This is the one copy:
// it capitalises words the same way, except that the abbreviations a bank's risk team
// writes in capitals stay in capitals.

const ACRONYMS = new Set([
  // risk, audit and assurance
  "rcsa", "kri", "kris", "kpi", "bia", "bcp", "dr", "rto", "rpo", "icfr", "coso", "erm",
  "fair", "ale", "sle", "aro", "ccm", "sla", "tat", "capa",
  // financial crime and privacy
  "aml", "cft", "sar", "str", "kyc", "cdd", "edd", "pep", "dsar", "dpia", "dpo", "ropa",
  "gdpr", "pii",
  // standards and regulators
  "iso", "iec", "pci", "dss", "nist", "csf", "soc", "cis", "hipaa", "sbp", "etgrm", "secp",
  "sama", "nca", "ecc", "cbo", "esg",
  // technology
  "it", "ict", "ot", "ai", "api", "sso", "mfa", "totp", "ldap", "ip", "url", "edr", "mdm",
  "cmdb", "uat", "vpn", "siem", "soc2",
  // roles and misc
  "ciso", "cro", "cfo", "ceo", "cio", "hr", "id", "pdf", "csv", "xlsx", "pkr", "usd",
]);

/** "rcsa_assessment" → "RCSA Assessment"; "it_asset" → "IT Asset"; "annual" → "Annual". */
export function titleCase(value: string | null | undefined): string {
  return (value ?? "")
    .replace(/_/g, " ")
    .replace(/\b[\w']+/g, (word) =>
      ACRONYMS.has(word.toLowerCase())
        ? word.toUpperCase()
        : word.charAt(0).toUpperCase() + word.slice(1),
    );
}

/** Sentence case for a stored key: "not_applicable" → "Not applicable", "sar" → "SAR". */
export function sentenceCase(value: string | null | undefined): string {
  const words = (value ?? "").replace(/_/g, " ").split(/(\s+)/);
  let first = true;
  return words
    .map((word) => {
      if (!/\w/.test(word)) return word;
      const lower = word.toLowerCase();
      if (ACRONYMS.has(lower)) {
        first = false;
        return word.toUpperCase();
      }
      const out = first ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
      first = false;
      return out;
    })
    .join("");
}

const FREQUENCY_ADVERBS: Record<string, string> = {
  continuous: "Continuously",
  daily: "Daily",
  weekly: "Weekly",
  fortnightly: "Every two weeks",
  monthly: "Monthly",
  quarterly: "Quarterly",
  semiannual: "Twice a year",
  annual: "Annually",
};

/** "annual" → "Annually"; "none" or unknown → "". Never "every annual". */
export function frequencyAdverb(value: string | null | undefined): string {
  return FREQUENCY_ADVERBS[(value ?? "").toLowerCase()] ?? "";
}
