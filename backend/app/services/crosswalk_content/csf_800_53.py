"""NIST CSF 2.0 → NIST SP 800-53 Rev. 5.

NIST publishes informative references from CSF 2.0 subcategories to SP 800-53 Rev. 5
controls in the Cybersecurity and Privacy Reference Tool (CPRT). These rows follow those
references, restricted to controls in the library's 800-53 template (base controls; an
enhancement NIST cites, such as AC-2(12), is recorded against its base control and marked
``related``). A subcategory is an outcome and a control is one way to reach it, so rows
are ``intersects`` where the control is a principal means of the outcome and ``related``
where it contributes; ``equivalent`` only where the two say the same thing (awareness
training, role-based training, backup, data at rest and in transit, identity proofing).
"""

FROM = "nist-csf-2.0"
TO = "nist-800-53-r5"
SOURCE = "NIST CPRT: CSF 2.0 informative references to SP 800-53 Rev. 5"

ROWS = """
# ---- GOVERN
GV.OC-01  PM-11  intersects  0.8   Mission and business processes are defined
GV.OC-01  PM-7   related     0.6   Enterprise architecture reflects the mission
GV.OC-02  PM-9   related     0.6   Risk strategy reflects stakeholder expectations
GV.OC-02  PM-11  related     0.6   Business process definitions consider stakeholders
GV.OC-03  PM-28  related     0.6   Risk framing records legal and regulatory constraints
GV.OC-04  PM-11  intersects  0.7   Critical objectives and services are defined
GV.OC-04  PM-8   related     0.6   Critical infrastructure plan
GV.OC-04  CP-2   related     0.6   Contingency plan identifies essential functions
GV.OC-05  RA-9   related     0.65  Criticality analysis covers dependencies
GV.OC-05  CP-2   related     0.6   Contingency planning identifies dependencies
GV.RM-01  PM-9   intersects  0.8   Risk management strategy sets objectives
GV.RM-02  PM-9   intersects  0.75  Strategy states risk tolerance
GV.RM-02  PM-28  intersects  0.75  Risk framing states tolerance
GV.RM-03  PM-9   related     0.65  Security risk within enterprise risk management
GV.RM-03  PM-28  related     0.6   Risk framing across the organisation
GV.RM-04  PM-9   related     0.65  Strategy directs risk response
GV.RM-04  PM-28  related     0.65  Risk framing covers response options
GV.RM-05  PM-29  related     0.6   Risk management roles communicate risk
GV.RM-06  RA-3   related     0.65  A consistent risk assessment method
GV.RM-06  PM-28  related     0.6   Risk framing sets assessment assumptions
GV.RR-01  PM-2   intersects  0.75  A senior official leads the security programme
GV.RR-01  PM-29  related     0.65  Risk leadership roles
GV.RR-02  PS-9   intersects  0.7   Position descriptions carry security roles
GV.RR-02  PM-2   related     0.6   Programme leadership role
GV.RR-02  PM-29  related     0.6   Risk management leadership roles
GV.RR-03  PM-3   equivalent  0.8   Resources for the security programme
GV.RR-03  SA-2   intersects  0.75  Resources allocated to protect systems
GV.RR-04  PS-1   intersects  0.7   Personnel security policy and procedures
GV.RR-04  PS-3   related     0.65  Screening is one HR practice
GV.RR-04  PS-4   related     0.65  Termination is one HR practice
GV.RR-04  PS-5   related     0.6   Transfer is one HR practice
GV.RR-04  PS-7   related     0.6   External personnel security
GV.RR-04  PS-8   related     0.6   Sanctions are one HR practice
GV.PO-01  PM-1   intersects  0.8   The security programme plan and policy
GV.PO-02  PM-1   intersects  0.75  Policy is reviewed and updated
GV.OV-01  PM-6   related     0.6   Measures show whether the strategy works
GV.OV-01  PM-9   related     0.6   Strategy is reviewed
GV.OV-02  PM-9   related     0.6   Strategy coverage is reviewed
GV.OV-03  PM-6   intersects  0.8   Performance is measured
GV.SC-01  PM-30  intersects  0.8   Supply chain risk management strategy
GV.SC-01  SR-1   intersects  0.75  Supply chain policy and procedures
GV.SC-01  SR-2   intersects  0.8   Supply chain risk management plan
GV.SC-02  SA-9   related     0.6   Roles with external service providers
GV.SC-03  PM-30  intersects  0.7   Supply chain risk within enterprise risk management
GV.SC-03  SR-3   related     0.65  Supply chain controls and processes
GV.SC-04  RA-9   intersects  0.7   Suppliers prioritised by criticality
GV.SC-05  SA-4   intersects  0.8   Security requirements in acquisition contracts
GV.SC-05  SA-9   intersects  0.7   Requirements for external services
GV.SC-05  SR-3   intersects  0.7   Supply chain requirements
GV.SC-06  SR-6   intersects  0.8   Suppliers are assessed
GV.SC-06  SA-4   related     0.6   Acquisition evaluates suppliers
GV.SC-07  SA-9   intersects  0.75  External service providers are monitored
GV.SC-07  SR-6   intersects  0.7   Supplier reviews continue
GV.SC-08  SR-8   intersects  0.75  Suppliers notify incidents
GV.SC-08  IR-4   related     0.65  Incident handling includes suppliers
GV.SC-09  PM-30  related     0.6   Supply chain practices are monitored
GV.SC-10  SA-9   related     0.6   Arrangements when a service ends
# ---- IDENTIFY
ID.AM-01  CM-8   intersects  0.85  Component inventory includes hardware
ID.AM-01  PM-5   related     0.65  System inventory
ID.AM-02  CM-8   intersects  0.8   Component inventory includes software
ID.AM-02  CM-10  related     0.6   Software usage is tracked
ID.AM-03  AC-4   intersects  0.75  Information flows are defined
ID.AM-03  CA-9   intersects  0.7   Internal connections are documented
ID.AM-03  CA-3   related     0.65  Information exchanges are documented
ID.AM-03  PL-8   related     0.65  Architecture shows communication
ID.AM-04  SA-9   intersects  0.75  External services are known
ID.AM-05  RA-2   intersects  0.8   Security categorisation drives priority
ID.AM-05  RA-9   intersects  0.75  Criticality analysis
ID.AM-07  CM-12  intersects  0.8   Information location is recorded
ID.AM-07  CM-13  related     0.65  Data actions are mapped
ID.AM-08  SA-3   related     0.65  System life cycle
ID.AM-08  CM-8   related     0.6   Inventory is kept current through the life cycle
ID.AM-08  MA-2   related     0.6   Maintenance through the life cycle
ID.AM-08  MP-6   related     0.6   Media sanitisation at end of life
ID.AM-08  SR-12  related     0.6   Component disposal
ID.RA-01  RA-5   intersects  0.85  Vulnerabilities are scanned for and identified
ID.RA-01  CA-2   related     0.6   Assessments find weaknesses
ID.RA-01  CA-7   related     0.6   Continuous monitoring finds weaknesses
ID.RA-02  PM-16  intersects  0.8   Threat awareness programme
ID.RA-02  SI-5   intersects  0.8   Security alerts and advisories are received
ID.RA-02  PM-15  related     0.65  Security groups and associations
ID.RA-03  RA-3   intersects  0.75  Risk assessment identifies threats
ID.RA-03  PM-12  related     0.6   Insider threat programme
ID.RA-03  PM-16  related     0.6   Threat awareness
ID.RA-04  RA-3   intersects  0.8   Likelihood and impact are assessed
ID.RA-04  RA-2   related     0.6   Impact levels are categorised
ID.RA-05  RA-3   intersects  0.8   Risk is determined and prioritised
ID.RA-05  PM-9   related     0.6   Strategy guides prioritisation
ID.RA-06  RA-7   equivalent  0.8   Risk responses are chosen and tracked
ID.RA-06  CA-5   intersects  0.75  Plans of action and milestones
ID.RA-06  PM-4   intersects  0.7   The POA&M process
ID.RA-07  CM-3   intersects  0.75  Changes are controlled
ID.RA-07  CM-4   intersects  0.75  Changes are analysed for security impact
ID.RA-08  RA-5   intersects  0.7   Receiving and handling disclosed vulnerabilities
ID.RA-08  SI-5   related     0.6   Advisories are acted on
ID.RA-09  SI-7   intersects  0.8   Software and firmware integrity is verified
ID.RA-09  SR-11  intersects  0.7   Component authenticity
ID.RA-09  SR-4   related     0.6   Provenance
ID.RA-10  SR-6   intersects  0.75  Critical suppliers are assessed
ID.RA-10  SA-9   related     0.6   External service risk
ID.IM-01  CA-2   related     0.6   Assessments lead to improvements
ID.IM-01  CA-5   related     0.6   Plans of action track improvements
ID.IM-01  PM-4   related     0.6   POA&M process
ID.IM-02  CP-4   related     0.65  Contingency plan tests find improvements
ID.IM-02  IR-3   related     0.65  Incident response tests find improvements
ID.IM-02  CA-8   related     0.6   Penetration tests find improvements
ID.IM-03  IR-4   related     0.6   Lessons learned from incident handling
ID.IM-03  CA-7   related     0.6   Monitoring results inform improvement
ID.IM-04  IR-8   intersects  0.8   Incident response plan maintained
ID.IM-04  CP-2   intersects  0.8   Contingency plan maintained
# ---- PROTECT
PR.AA-01  AC-2   intersects  0.8   Accounts are managed
PR.AA-01  IA-4   intersects  0.8   Identifiers are managed
PR.AA-01  IA-5   intersects  0.8   Authenticators are managed
PR.AA-02  IA-12  equivalent  0.85  Identities are proofed and bound to credentials
PR.AA-03  IA-2   intersects  0.85  Organisational users are authenticated
PR.AA-03  IA-8   intersects  0.75  Non-organisational users are authenticated
PR.AA-03  IA-3   related     0.65  Devices are authenticated
PR.AA-03  IA-11  related     0.6   Re-authentication
PR.AA-03  AC-7   related     0.6   Unsuccessful logon attempts
PR.AA-04  SC-23  related     0.6   Session authenticity protects assertions
PR.AA-05  AC-3   intersects  0.8   Access is enforced
PR.AA-05  AC-6   intersects  0.85  Least privilege
PR.AA-05  AC-5   intersects  0.75  Separation of duties
PR.AA-05  AC-2   intersects  0.7   Account authorisations
PR.AA-05  AC-17  related     0.6   Remote access permissions
PR.AA-05  AC-24  related     0.6   Access control decisions
PR.AA-06  PE-2   intersects  0.8   Physical access authorisations
PR.AA-06  PE-3   intersects  0.8   Physical access control
PR.AA-06  PE-6   related     0.65  Monitoring physical access
PR.AA-06  PE-8   related     0.6   Visitor access records
PR.AT-01  AT-2   equivalent  0.85  Literacy training and awareness for all users
PR.AT-02  AT-3   equivalent  0.85  Role-based training
PR.DS-01  SC-28  equivalent  0.85  Information at rest is protected
PR.DS-01  MP-4   related     0.6   Media storage
PR.DS-01  MP-2   related     0.6   Media access
PR.DS-02  SC-8   equivalent  0.85  Transmission confidentiality and integrity
PR.DS-02  SC-13  related     0.6   Cryptographic protection
PR.DS-10  SC-4   related     0.65  Information in shared resources
PR.DS-10  SC-39  related     0.6   Process isolation
PR.DS-10  SI-16  related     0.6   Memory protection
PR.DS-11  CP-9   equivalent  0.9   System backup
PR.PS-01  CM-2   intersects  0.85  Baseline configuration
PR.PS-01  CM-6   intersects  0.85  Configuration settings
PR.PS-01  CM-3   intersects  0.7   Configuration change control
PR.PS-01  CM-7   related     0.65  Least functionality
PR.PS-01  CM-9   related     0.65  Configuration management plan
PR.PS-02  SI-2   intersects  0.85  Flaw remediation
PR.PS-02  SA-22  intersects  0.7   Unsupported components are replaced
PR.PS-02  CM-3   related     0.6   Updates go through change control
PR.PS-03  MA-2   intersects  0.8   Controlled maintenance
PR.PS-03  MA-6   related     0.65  Timely maintenance
PR.PS-03  SA-22  related     0.6   Unsupported hardware
PR.PS-04  AU-2   intersects  0.85  Event logging
PR.PS-04  AU-3   intersects  0.75  Content of audit records
PR.PS-04  AU-12  intersects  0.85  Audit record generation
PR.PS-05  CM-7   intersects  0.75  Least functionality prevents unauthorised software
PR.PS-05  CM-11  intersects  0.75  User-installed software
PR.PS-05  CM-10  related     0.65  Software usage restrictions
PR.PS-05  SI-7   related     0.6   Integrity checks detect unauthorised software
PR.PS-06  SA-3   intersects  0.8   System development life cycle
PR.PS-06  SA-8   intersects  0.75  Security engineering principles
PR.PS-06  SA-11  intersects  0.75  Developer testing
PR.PS-06  SA-15  intersects  0.75  Development process, standards and tools
PR.PS-06  SA-10  related     0.6   Developer configuration management
PR.IR-01  SC-7   intersects  0.85  Boundary protection
PR.IR-01  AC-4   intersects  0.75  Information flow enforcement
PR.IR-01  SC-32  related     0.6   System partitioning
PR.IR-01  AC-17  related     0.6   Remote access
PR.IR-01  AC-18  related     0.6   Wireless access
PR.IR-02  PE-13  intersects  0.8   Fire protection
PR.IR-02  PE-14  intersects  0.8   Environmental controls
PR.IR-02  PE-15  intersects  0.75  Water damage protection
PR.IR-02  PE-11  related     0.65  Emergency power
PR.IR-02  PE-9   related     0.6   Power equipment and cabling
PR.IR-02  PE-23  related     0.6   Facility location
PR.IR-03  CP-7   intersects  0.75  Alternate processing site
PR.IR-03  CP-6   related     0.65  Alternate storage site
PR.IR-03  CP-8   related     0.65  Telecommunications services
PR.IR-03  CP-11  related     0.6   Alternate communications protocols
PR.IR-03  SC-6   related     0.6   Resource availability
PR.IR-03  SC-5   related     0.6   Denial-of-service protection
PR.IR-03  SC-36  related     0.6   Distributed processing and storage
PR.IR-04  SC-6   intersects  0.7   Resource availability
PR.IR-04  AU-4   related     0.6   Audit log storage capacity
PR.IR-04  CP-2   related     0.6   Capacity planning in the contingency plan
PR.IR-04  SC-5   related     0.6   Denial-of-service protection
# ---- DETECT
DE.CM-01  SI-4   intersects  0.85  System monitoring includes networks
DE.CM-01  AU-12  related     0.6   Audit records support monitoring
DE.CM-01  SC-7   related     0.6   Boundary monitoring
DE.CM-01  CA-7   related     0.6   Continuous monitoring
DE.CM-02  PE-6   equivalent  0.85  Monitoring physical access
DE.CM-02  PE-20  related     0.6   Asset monitoring and tracking
DE.CM-03  SI-4   intersects  0.7   Monitoring user activity
DE.CM-03  AC-2   related     0.6   Account monitoring for atypical use
DE.CM-03  CA-7   related     0.6   Continuous monitoring
DE.CM-06  SA-9   intersects  0.7   External service providers are monitored
DE.CM-06  PS-7   intersects  0.7   External personnel are monitored
DE.CM-06  SI-4   related     0.6   System monitoring
DE.CM-09  SI-4   intersects  0.75  System monitoring
DE.CM-09  SI-3   intersects  0.75  Malicious code protection
DE.CM-09  SI-7   intersects  0.7   Integrity monitoring
DE.AE-02  AU-6   intersects  0.8   Audit review and analysis
DE.AE-02  SI-4   intersects  0.7   Monitoring analyses events
DE.AE-02  IR-4   related     0.65  Incident handling analyses events
DE.AE-03  AU-6   intersects  0.75  Correlating audit repositories
DE.AE-03  SI-4   related     0.65  Correlating monitoring information
DE.AE-03  IR-4   related     0.6   Correlating incident information
DE.AE-04  IR-4   intersects  0.7   Impact and scope are analysed
DE.AE-04  SI-4   related     0.6   Monitoring informs scope
DE.AE-06  AU-6   intersects  0.7   Findings are reported to the right people
DE.AE-06  SI-4   intersects  0.7   Monitoring information is provided to staff
DE.AE-06  IR-4   related     0.6   Incident handling information
DE.AE-07  PM-16  intersects  0.75  Threat awareness feeds analysis
DE.AE-07  SI-5   intersects  0.7   Advisories feed analysis
DE.AE-07  RA-10  related     0.65  Threat hunting uses threat intelligence
DE.AE-08  IR-4   intersects  0.75  Incidents are declared and handled
DE.AE-08  IR-8   related     0.65  The plan defines what an incident is
# ---- RESPOND
RS.MA-01  IR-4   intersects  0.8   Incident handling
RS.MA-01  IR-8   intersects  0.8   Incident response plan
RS.MA-02  IR-4   intersects  0.7   Reports are triaged in handling
RS.MA-02  IR-5   related     0.6   Incidents are tracked
RS.MA-03  IR-4   intersects  0.7   Incidents are categorised
RS.MA-03  IR-5   related     0.6   Incident monitoring
RS.MA-03  IR-8   related     0.6   The plan defines categories
RS.MA-04  IR-4   intersects  0.7   Escalation during handling
RS.MA-04  IR-6   related     0.6   Incident reporting
RS.MA-04  IR-7   related     0.6   Response assistance
RS.MA-05  IR-4   related     0.6   Recovery starts as handling concludes
RS.MA-05  CP-10  related     0.6   Recovery and reconstitution
RS.AN-03  IR-4   intersects  0.75  Analysis establishes root cause
RS.AN-06  IR-5   intersects  0.75  Incident actions are recorded
RS.AN-06  IR-4   related     0.6   Handling records
RS.AN-06  AU-7   related     0.6   Audit reduction supports investigation
RS.AN-07  AU-9   intersects  0.7   Audit information integrity is protected
RS.AN-07  IR-4   related     0.6   Evidence is preserved in handling
RS.AN-08  IR-4   intersects  0.7   Magnitude is estimated in handling
RS.CO-02  IR-6   intersects  0.8   Incidents are reported to stakeholders
RS.CO-02  IR-7   related     0.6   Response assistance
RS.CO-03  IR-6   intersects  0.7   Information is shared with designated parties
RS.CO-03  PM-15  related     0.6   Security groups share information
RS.CO-03  SI-5   related     0.6   Advisories are shared
RS.CO-03  IR-4   related     0.6   Coordination during handling
RS.MI-01  IR-4   intersects  0.8   Containment
RS.MI-02  IR-4   intersects  0.8   Eradication
# ---- RECOVER
RC.RP-01  CP-10  intersects  0.8   Recovery and reconstitution
RC.RP-01  CP-2   related     0.65  The contingency plan is executed
RC.RP-01  IR-4   related     0.65  Recovery is part of incident handling
RC.RP-02  CP-10  intersects  0.75  Recovery actions
RC.RP-02  IR-4   related     0.6   Recovery during handling
RC.RP-03  CP-9   intersects  0.75  Backups are tested for reliability and integrity
RC.RP-03  CP-4   related     0.6   Contingency plan testing
RC.RP-04  CP-2   related     0.6   Post-incident operational norms
RC.RP-04  CP-10  related     0.6   Reconstitution to a known state
RC.RP-05  CP-10  intersects  0.7   Restored assets are verified
RC.RP-06  CP-10  related     0.65  Recovery is declared complete
RC.RP-06  IR-4   related     0.6   Handling closes
RC.CO-03  CP-2   related     0.6   Recovery communications
RC.CO-03  IR-4   related     0.6   Coordination with stakeholders
RC.CO-04  CP-2   related     0.55  Public communications in the plan
"""
