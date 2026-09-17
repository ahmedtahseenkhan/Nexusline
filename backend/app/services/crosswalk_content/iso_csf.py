"""ISO/IEC 27001:2022 (clauses 4-10 and Annex A) → NIST Cybersecurity Framework 2.0.

Matched on what each clause and subcategory asks for. CSF 2.0 subcategories are outcomes,
usually broader than one Annex A control, so most rows are ``intersects``; ``equivalent``
is kept for the pairs where the core obligation is the same (policy, backup, capacity,
logging, secure authentication, configuration management). An umbrella outcome such as
GV.RR-04 (cybersecurity in HR practices) is never marked as containing a specific
control, because an assured control on the umbrella need not implement that control.
"""

FROM = "iso-27001-2022"
TO = "nist-csf-2.0"
SOURCE = "NexusLine curated; informed by the NIST CSF 2.0 informative references (CPRT)"

ROWS = """
# ---- clauses 4-10
4.1      GV.OC-01  intersects  0.75  Context of the organisation and its mission inform security
4.1      GV.OC-05  related     0.6   External and internal issues include dependencies
4.2      GV.OC-02  equivalent  0.8   Needs and expectations of interested parties are understood
4.2      GV.OC-03  related     0.6   Interested-party requirements include legal and regulatory ones
5.1      GV.RR-01  equivalent  0.8   Top management is accountable for and leads information security
5.2      GV.PO-01  intersects  0.75  The ISMS policy is set by top management; CSF asks for a cybersecurity policy
5.3      GV.RR-02  intersects  0.75  Roles, responsibilities and authorities are assigned and communicated
6.1.1    GV.RM-01  intersects  0.7   Planning to address risks sets risk management objectives
6.1.1    GV.RM-03  related     0.6   Security risk planning within enterprise risk management
6.1.2    GV.RM-02  intersects  0.7   Risk acceptance criteria express risk appetite and tolerance
6.1.2    GV.RM-06  intersects  0.75  A defined method gives consistent, comparable risk results
6.1.2    ID.RA-03  related     0.6   Risk identification considers threats
6.1.2    ID.RA-04  intersects  0.75  Likelihood and consequences are assessed
6.1.2    ID.RA-05  intersects  0.75  Risks are analysed and prioritised for treatment
6.1.3    ID.RA-06  intersects  0.75  Risk treatment options are chosen, planned and tracked
6.2      GV.RM-01  related     0.6   Security objectives and plans to achieve them
6.3      ID.RA-07  related     0.6   Changes to the ISMS are planned
7.1      GV.RR-03  equivalent  0.8   Resources needed for security are determined and provided
7.2      GV.RR-04  related     0.6   Competence is part of HR practice
7.2      PR.AT-02  related     0.6   Competence of people in specialised roles
7.3      PR.AT-01  intersects  0.75  Personnel are aware of the policy and their contribution
7.4      GV.RM-05  related     0.6   Internal and external communication about security and risk
8.2      ID.RA-05  related     0.6   Risk assessments are performed at planned intervals
8.3      ID.RA-06  related     0.6   The risk treatment plan is implemented
9.1      GV.OV-03  intersects  0.7   Security performance and effectiveness are evaluated
9.2.1    ID.IM-01  related     0.6   Internal audits identify improvements
9.3.1    GV.OV-01  intersects  0.7   Management reviews the ISMS and its outcomes
9.3.2    GV.OV-02  related     0.6   Review inputs cover the risk strategy's scope
10.1     ID.IM-01  intersects  0.7   Continual improvement from evaluations
10.1     ID.IM-03  related     0.6   Improvement from operational experience
10.2     ID.IM-03  related     0.6   Corrective action on nonconformities
# ---- Annex A 5 organisational
A.5.1    GV.PO-01  equivalent  0.85  An approved, published information security policy
A.5.1    GV.PO-02  intersects  0.75  Policies reviewed at planned intervals and on change
A.5.2    GV.RR-02  equivalent  0.8   Security roles and responsibilities defined and allocated
A.5.3    PR.AA-05  intersects  0.7   PR.AA-05 includes separation of duties in access permissions
A.5.4    GV.RR-01  related     0.6   Management requires personnel to apply security
A.5.5    RS.CO-03  related     0.6   Contact with authorities supports information sharing
A.5.6    ID.RA-02  related     0.6   Special interest groups are a source of threat information
A.5.7    ID.RA-02  intersects  0.8   Threat intelligence is collected from sources
A.5.7    ID.RA-03  related     0.6   Threat intelligence informs threat identification
A.5.7    DE.AE-07  intersects  0.75  Threat intelligence is used in analysis
A.5.9    ID.AM-01  superset    0.75  The asset inventory includes hardware
A.5.9    ID.AM-02  superset    0.75  The asset inventory includes software
A.5.9    ID.AM-07  intersects  0.7   The inventory includes information assets
A.5.11   ID.AM-08  related     0.6   Asset return is part of the asset life cycle
A.5.12   ID.AM-05  intersects  0.7   Classification drives asset prioritisation
A.5.14   PR.DS-02  intersects  0.75  Information transferred is protected
A.5.15   PR.AA-05  intersects  0.8   Access rules based on business and security requirements
A.5.16   PR.AA-01  intersects  0.85  Identities are managed through their life cycle
A.5.17   PR.AA-01  intersects  0.8   Authentication information (credentials) is managed
A.5.18   PR.AA-05  intersects  0.8   Access rights provisioned, reviewed and removed
A.5.19   GV.SC-01  intersects  0.75  Supplier security processes are established
A.5.19   GV.SC-03  related     0.6   Supplier risk within the security programme
A.5.19   GV.SC-04  related     0.6   Suppliers are identified by the risk they carry
A.5.19   GV.SC-06  intersects  0.7   Supplier risk is assessed before engagement
A.5.19   ID.AM-04  related     0.65  Supplier services are known
A.5.20   GV.SC-05  equivalent  0.85  Security requirements are written into supplier agreements
A.5.21   GV.SC-01  intersects  0.7   ICT supply chain risk is managed
A.5.22   GV.SC-07  intersects  0.8   Supplier services and their risk are monitored
A.5.22   DE.CM-06  intersects  0.75  Service provider activity is monitored
A.5.23   GV.SC-05  related     0.6   Cloud service security requirements
A.5.24   ID.IM-04  intersects  0.75  Incident response plans and procedures are prepared
A.5.24   RS.MA-01  intersects  0.7   The incident response plan is in place to execute
A.5.25   DE.AE-02  intersects  0.75  Events are assessed
A.5.25   DE.AE-08  intersects  0.75  An event is declared an incident against criteria
A.5.25   RS.MA-03  intersects  0.7   Incidents are categorised
A.5.26   RS.MA-01  intersects  0.8   Incidents are responded to per documented procedures
A.5.26   RS.MA-04  related     0.6   Escalation during response
A.5.26   RS.MI-01  related     0.65  Containment is part of response
A.5.26   RS.MI-02  related     0.65  Eradication is part of response
A.5.26   RS.CO-02  related     0.6   Stakeholders are notified during response
A.5.27   ID.IM-03  intersects  0.7   Lessons from incidents improve controls
A.5.27   RS.AN-03  related     0.65  Root causes inform learning
A.5.28   RS.AN-07  equivalent  0.75  Evidence is collected and its integrity preserved
A.5.29   PR.IR-03  related     0.6   Security is maintained during disruption
A.5.29   RC.RP-01  related     0.6   Recovery activities during disruption
A.5.30   PR.IR-03  intersects  0.75  ICT readiness provides resilience
A.5.30   RC.RP-01  related     0.6   ICT continuity plans are executed in recovery
A.5.31   GV.OC-03  equivalent  0.85  Legal, regulatory and contractual requirements are identified and managed
A.5.32   GV.OC-03  related     0.6   Intellectual property obligations are legal requirements
A.5.34   GV.OC-03  related     0.6   Privacy obligations are legal requirements
A.5.35   ID.IM-01  intersects  0.7   Independent reviews identify improvements
A.5.36   ID.IM-01  related     0.6   Compliance reviews identify improvements
# ---- Annex A 6 people
A.6.1    GV.RR-04  intersects  0.7   Screening is one HR practice CSF expects
A.6.2    GV.RR-04  intersects  0.7   Security in terms of employment
A.6.3    PR.AT-01  intersects  0.8   Security awareness and training for all personnel
A.6.3    PR.AT-02  intersects  0.75  Role-specific education and training
A.6.4    GV.RR-04  intersects  0.6   Disciplinary process as an HR practice
A.6.5    GV.RR-04  intersects  0.7   Offboarding and change of role
A.6.8    RS.MA-02  related     0.6   Reported events are triaged
A.6.8    DE.AE-06  related     0.6   Event information reaches the right people
# ---- Annex A 7 physical
A.7.1    PR.AA-06  intersects  0.75  Physical perimeters restrict physical access
A.7.2    PR.AA-06  intersects  0.8   Physical entry is controlled
A.7.3    PR.AA-06  intersects  0.7   Offices and rooms are secured
A.7.4    DE.CM-02  equivalent  0.85  Premises are monitored for unauthorised physical access
A.7.5    PR.IR-02  equivalent  0.8   Protection against physical and environmental threats
A.7.6    PR.AA-06  related     0.6   Working in secure areas
A.7.8    PR.IR-02  related     0.6   Equipment is sited against environmental threats
A.7.10   PR.DS-01  intersects  0.7   Data on storage media is protected
A.7.10   ID.AM-08  related     0.6   Media is managed through its life cycle
A.7.11   PR.IR-02  intersects  0.7   Supporting utilities protect against power and environmental failure
A.7.13   PR.PS-03  intersects  0.75  Equipment is maintained
A.7.14   ID.AM-08  intersects  0.7   Secure disposal at end of life
# ---- Annex A 8 technological
A.8.1    PR.PS-01  related     0.6   Endpoint devices are configured
A.8.1    PR.DS-01  related     0.6   Data on endpoints is protected
A.8.2    PR.AA-05  intersects  0.8   Privileged access is restricted and managed
A.8.3    PR.AA-05  intersects  0.8   Access to information is restricted per policy
A.8.4    PR.AA-05  related     0.6   Access to source code is restricted
A.8.4    PR.PS-06  related     0.6   Source code protection within secure development
A.8.5    PR.AA-03  equivalent  0.85  Users, services and hardware are authenticated securely
A.8.6    PR.IR-04  equivalent  0.85  Capacity is monitored and adjusted to need
A.8.7    PR.PS-05  intersects  0.65  Malicious software is prevented from running
A.8.7    DE.CM-09  intersects  0.7   Computing resources are monitored for malicious code
A.8.8    ID.RA-01  intersects  0.8   Technical vulnerabilities are identified
A.8.8    PR.PS-02  intersects  0.7   Software is patched to remove vulnerabilities
A.8.8    ID.RA-08  related     0.6   Vulnerability information from outside is received
A.8.9    PR.PS-01  equivalent  0.85  Configurations are established, applied and managed
A.8.10   ID.AM-08  related     0.6   Information deleted when no longer needed
A.8.11   PR.DS-01  related     0.6   Masking protects stored data
A.8.12   PR.DS-01  intersects  0.7   Leakage prevention for data at rest
A.8.12   PR.DS-02  intersects  0.7   Leakage prevention for data in transit
A.8.12   PR.DS-10  intersects  0.65  Leakage prevention for data in use
A.8.13   PR.DS-11  equivalent  0.9   Backups are created, protected, maintained and tested
A.8.13   RC.RP-03  related     0.65  Backup integrity is verified before restoring
A.8.14   PR.IR-03  equivalent  0.8   Redundancy provides resilience
A.8.15   PR.PS-04  equivalent  0.85  Logs are produced and kept for monitoring
A.8.16   DE.CM-01  intersects  0.8   Networks are monitored for anomalies
A.8.16   DE.CM-03  intersects  0.75  User activity is monitored
A.8.16   DE.CM-09  intersects  0.75  Systems are monitored
A.8.16   DE.AE-02  related     0.6   Anomalies found by monitoring are analysed
A.8.16   DE.AE-03  related     0.6   Monitoring sources are correlated
A.8.18   PR.AA-05  related     0.6   Privileged utilities are restricted
A.8.19   PR.PS-05  intersects  0.8   Only authorised software is installed
A.8.19   PR.PS-02  related     0.6   Software on operational systems is maintained
A.8.20   PR.IR-01  intersects  0.8   Networks are protected from unauthorised access
A.8.20   DE.CM-01  related     0.6   Network controls support monitoring
A.8.20   ID.AM-03  related     0.6   Network security needs the network mapped
A.8.21   PR.IR-01  related     0.6   Network services are secured
A.8.22   PR.IR-01  intersects  0.75  Networks are segmented
A.8.23   PR.IR-01  related     0.55  Web access is filtered
A.8.24   PR.DS-01  intersects  0.75  Cryptography protects data at rest
A.8.24   PR.DS-02  intersects  0.75  Cryptography protects data in transit
A.8.25   PR.PS-06  intersects  0.8   Secure development life cycle
A.8.26   PR.PS-06  related     0.6   Security requirements for applications
A.8.27   PR.PS-06  related     0.6   Secure architecture and engineering principles
A.8.28   PR.PS-06  intersects  0.75  Secure coding within secure development
A.8.29   PR.PS-06  intersects  0.7   Security testing within secure development
A.8.30   PR.PS-06  related     0.6   Outsourced development follows secure practice
A.8.31   PR.IR-01  related     0.6   Development, test and production are separated
A.8.32   ID.RA-07  intersects  0.75  Changes are assessed for risk, recorded and tracked
A.8.32   PR.PS-01  related     0.6   Configuration change is controlled
"""
