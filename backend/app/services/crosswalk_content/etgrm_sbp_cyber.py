"""SBP ETGRM Framework → SBP Cyber Security / Information Security Guidelines.

Both come from the State Bank of Pakistan and overlap heavily in information security.
Matched on the content of the two library templates. ETGRM pillar 3 (information
security) and the Cyber Security framework's protection section often name the same
control; those rows are ``equivalent``. Governance rows are ``intersects`` or
``related`` because ETGRM governs technology as a whole and the guidelines govern cyber
security.
"""

FROM = "sbp-etgrm"
TO = "sbp-cybersecurity"
SOURCE = "NexusLine curated"

ROWS = """
ETGRM-1.1   CS-1.1   intersects  0.75  Board oversight of technology and cyber risk
ETGRM-1.2   CS-1.2   related     0.6   Strategy
ETGRM-1.4   CS-1.4   related     0.65  Roles and responsibilities
ETGRM-1.5   CS-1.2   related     0.6   Policy framework
ETGRM-1.7   CS-1.9   intersects  0.7   Budget and resources
ETGRM-1.8   CS-1.7   intersects  0.7   Metrics reported to management and board
ETGRM-1.9   CS-1.6   intersects  0.75  Regulatory compliance
ETGRM-1.10  CS-8.2   related     0.6   Skills of technology staff
ETGRM-2.2   CS-1.5   intersects  0.7   Risk appetite
ETGRM-2.3   CS-2.7   intersects  0.7   Risk register
ETGRM-2.4   CS-2.3   intersects  0.75  Risk assessment
ETGRM-2.5   CS-2.7   intersects  0.7   Risk treatment tracked
ETGRM-2.8   CS-7.6   intersects  0.7   Concentration risk
ETGRM-3.1   CS-1.2   intersects  0.75  Information security policy
ETGRM-3.2   CS-1.3   equivalent  0.85  CISO and security function
ETGRM-3.3   CS-2.2   equivalent  0.8   Classification of information assets
ETGRM-3.4   CS-3.1   intersects  0.8   Least privilege and role-based access
ETGRM-3.4   CS-3.2   intersects  0.75  Periodic access reviews
ETGRM-3.5   CS-3.3   intersects  0.8   Multi-factor authentication
ETGRM-3.5   CS-3.4   intersects  0.8   Privileged accounts
ETGRM-3.6   CS-3.5   intersects  0.8   Firewalls and segmentation
ETGRM-3.6   CS-3.6   intersects  0.75  Secure remote access
ETGRM-3.6   CS-4.4   related     0.65  Intrusion prevention
ETGRM-3.7   CS-3.7   equivalent  0.85  Endpoint hardening and anti-malware
ETGRM-3.7   CS-3.9   related     0.65  Configuration management
ETGRM-3.8   CS-3.10  equivalent  0.9   Cryptography and key management
ETGRM-3.9   CS-2.5   intersects  0.8   Vulnerability scanning and testing
ETGRM-3.9   CS-3.8   intersects  0.8   Timely remediation
ETGRM-3.9   CS-4.9   related     0.65  Penetration testing
ETGRM-3.10  CS-4.2   intersects  0.75  Log collection and analysis
ETGRM-3.10  CS-4.3   intersects  0.75  Monitoring for unauthorised activity
ETGRM-3.10  CS-4.5   intersects  0.75  Log retention
ETGRM-3.11  CS-3.11  intersects  0.7   Protection of customer data
ETGRM-3.11  CS-3.12  equivalent  0.85  Data loss prevention
ETGRM-4.3   CS-2.1   intersects  0.8   Asset inventory
ETGRM-4.3   CS-3.9   related     0.65  Configurations managed
ETGRM-4.5   CS-5.1   related     0.6   Incident management
ETGRM-4.6   CS-6.3   intersects  0.8   Backups
ETGRM-4.7   CS-3.15  equivalent  0.8   Physical and environmental security of facilities
ETGRM-4.9   CS-3.8   intersects  0.75  Patching
ETGRM-5.4   CS-3.14  intersects  0.75  Secure development
ETGRM-5.5   CS-3.14  related     0.6   Security testing of applications
ETGRM-6.1   CS-6.1   related     0.65  Continuity and resilience policy
ETGRM-6.1   CS-6.5   intersects  0.7   Cyber recovery within continuity
ETGRM-6.3   CS-6.2   intersects  0.8   RTO and RPO
ETGRM-6.6   CS-6.4   intersects  0.75  Recovery tested
ETGRM-6.7   CS-6.6   related     0.6   Communication in a crisis
ETGRM-7.2   CS-7.1   intersects  0.7   Third-party risk assessed
ETGRM-7.3   CS-7.2   equivalent  0.8   Vendor due diligence
ETGRM-7.4   CS-7.3   intersects  0.8   Security requirements in contracts
ETGRM-7.5   CS-7.4   intersects  0.8   Providers monitored
ETGRM-7.6   CS-7.5   related     0.65  Protecting data and access with providers
ETGRM-8.1   CS-1.8   related     0.65  Independent audit
ETGRM-8.3   CS-1.8   intersects  0.7   Audit of information security
ETGRM-8.5   CS-7.4   related     0.6   Independent assurance over providers
"""
