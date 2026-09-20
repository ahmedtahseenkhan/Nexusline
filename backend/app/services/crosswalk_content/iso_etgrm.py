"""ISO/IEC 27001:2022 → SBP Enterprise Technology Governance & Risk Management Framework.

No published mapping exists. Rows are matched on the content of the library's ETGRM
clauses (the SBP framework as summarised in the template) against ISO clauses and Annex A
controls. ETGRM speaks to technology governance as a whole, so security-specific ISO
controls usually meet part of an ETGRM clause (``intersects``). ``equivalent`` only where
the two clearly ask for the same thing: segregation of duties, regulatory compliance,
the information security policy, cryptography, change management, capacity, backup and
redundancy.
"""

FROM = "iso-27001-2022"
TO = "sbp-etgrm"
SOURCE = "NexusLine curated"

ROWS = """
5.1      ETGRM-1.1   related     0.6   Top management and board oversight of technology risk
5.3      ETGRM-1.4   intersects  0.7   Roles, responsibilities and reporting lines
5.2      ETGRM-1.5   related     0.6   Policy framework
6.1.1    ETGRM-2.1   intersects  0.7   Risk management integrated with the organisation's processes
6.1.2    ETGRM-2.2   related     0.6   Risk acceptance criteria and appetite
6.1.2    ETGRM-2.3   intersects  0.7   Risks identified
6.1.2    ETGRM-2.4   intersects  0.8   Likelihood and impact assessed by a consistent method
6.1.3    ETGRM-2.5   intersects  0.8   Risk treatment selected and implemented
6.3      ETGRM-2.7   related     0.6   Changes planned with their risk in mind
7.1      ETGRM-1.7   intersects  0.75  Resources provided
7.2      ETGRM-1.10  intersects  0.75  Competence maintained
8.3      ETGRM-2.5   related     0.65  Risk treatment implemented
9.1      ETGRM-1.8   intersects  0.7   Performance measured and reported
9.1      ETGRM-2.6   related     0.6   Risk and control effectiveness monitored
9.2.1    ETGRM-8.1   intersects  0.7   Internal audit function
9.2.2    ETGRM-8.2   intersects  0.7   Audit programme
10.2     ETGRM-8.4   related     0.65  Findings tracked to correction
A.5.1    ETGRM-1.5   intersects  0.75  Policies approved and reviewed
A.5.1    ETGRM-3.1   equivalent  0.85  Information security policy
A.5.2    ETGRM-1.4   intersects  0.7   Security roles in the technology organisation
A.5.2    ETGRM-3.2   related     0.65  Security function and its lead
A.5.3    ETGRM-1.6   equivalent  0.85  Segregation of duties
A.5.8    ETGRM-5.1   related     0.65  Security in project management
A.5.9    ETGRM-4.3   intersects  0.75  Asset inventory
A.5.12   ETGRM-3.3   intersects  0.8   Classification of information
A.5.13   ETGRM-3.3   intersects  0.7   Labelling and handling
A.5.15   ETGRM-3.4   intersects  0.8   Access control on least privilege and need to know
A.5.16   ETGRM-3.4   related     0.65  Identity management
A.5.18   ETGRM-3.4   intersects  0.75  Access rights reviewed
A.5.19   ETGRM-5.6   related     0.6   Vendor evaluation
A.5.19   ETGRM-7.1   intersects  0.7   Supplier security policy
A.5.19   ETGRM-7.2   related     0.65  Risk assessed before engaging a supplier
A.5.19   ETGRM-7.3   intersects  0.7   Supplier due diligence
A.5.20   ETGRM-7.4   intersects  0.8   Security requirements in agreements
A.5.20   ETGRM-7.6   related     0.65  Data protection obligations on suppliers
A.5.21   ETGRM-7.6   related     0.6   ICT supply chain security
A.5.22   ETGRM-7.5   intersects  0.8   Supplier services monitored
A.5.23   ETGRM-7.7   intersects  0.8   Cloud services security
A.5.26   ETGRM-4.5   related     0.65  Incident handling
A.5.29   ETGRM-6.1   related     0.6   Security during disruption
A.5.30   ETGRM-6.1   intersects  0.7   ICT continuity policy and readiness
A.5.30   ETGRM-6.2   related     0.65  Continuity requirements from impact analysis
A.5.30   ETGRM-6.3   intersects  0.7   Recovery objectives
A.5.30   ETGRM-6.6   intersects  0.7   Continuity arrangements tested
A.5.30   ETGRM-6.8   related     0.6   Plans kept current
A.5.31   ETGRM-1.9   equivalent  0.8   Legal, regulatory and contractual requirements
A.5.35   ETGRM-8.3   related     0.6   Independent review of security
A.5.35   ETGRM-8.5   intersects  0.7   Independent assurance
A.5.37   ETGRM-1.5   related     0.65  Documented procedures
A.5.37   ETGRM-4.1   intersects  0.75  Operating procedures
A.6.7    ETGRM-3.6   related     0.6   Secure remote working
A.7.1    ETGRM-4.7   related     0.65  Physical perimeters of the data centre
A.7.2    ETGRM-4.7   related     0.65  Physical entry to the data centre
A.7.5    ETGRM-4.7   intersects  0.7   Environmental protection
A.7.11   ETGRM-4.7   intersects  0.7   Power and supporting utilities
A.8.1    ETGRM-3.7   intersects  0.7   Endpoint protection
A.8.2    ETGRM-3.5   intersects  0.8   Privileged access controlled
A.8.5    ETGRM-3.5   intersects  0.8   Strong authentication
A.8.6    ETGRM-4.4   equivalent  0.85  Capacity management
A.8.7    ETGRM-3.7   intersects  0.8   Malware protection
A.8.8    ETGRM-3.9   intersects  0.85  Vulnerability management
A.8.8    ETGRM-4.9   intersects  0.7   Patching
A.8.9    ETGRM-3.7   related     0.65  Hardening
A.8.9    ETGRM-4.3   intersects  0.7   Configuration management
A.8.12   ETGRM-3.11  intersects  0.8   Data leakage prevention
A.8.13   ETGRM-4.6   equivalent  0.85  Backup
A.8.14   ETGRM-6.4   related     0.6   Alternate processing capacity
A.8.14   ETGRM-6.5   equivalent  0.8   Redundancy of critical facilities
A.8.15   ETGRM-3.10  intersects  0.8   Security logging
A.8.16   ETGRM-3.10  intersects  0.8   Monitoring for unauthorised activity
A.8.19   ETGRM-4.9   related     0.65  Controlled installation of releases
A.8.20   ETGRM-3.6   intersects  0.8   Network security
A.8.22   ETGRM-3.6   intersects  0.7   Segmentation
A.8.24   ETGRM-3.8   equivalent  0.85  Cryptography and key management
A.8.25   ETGRM-5.4   intersects  0.8   Secure development life cycle
A.8.26   ETGRM-5.3   intersects  0.7   Security requirements in system requirements
A.8.28   ETGRM-5.4   related     0.65  Secure coding
A.8.29   ETGRM-5.5   intersects  0.75  Security and acceptance testing
A.8.30   ETGRM-5.6   related     0.6   Acquired and outsourced development
A.8.31   ETGRM-5.4   related     0.65  Separation of environments
A.8.32   ETGRM-4.2   equivalent  0.85  Change management
A.8.32   ETGRM-4.9   related     0.65  Releases through change control
A.8.33   ETGRM-5.5   related     0.65  Test data protects production information
"""
