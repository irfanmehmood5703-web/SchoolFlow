"""Original editable SchoolFlow documents; no real reference pupil data is seeded."""
DOCUMENTS = [
 ('student-card-new','Student Card New','SCN','card',True),
 ('student-card','Student Card','SC','card',False),
 ('guardian-card','Guardian Card','GC','card',True),
 ('school-leaving','School Leaving Certificate','SLC','document',True),
 ('character','Student Character Certificate','CHAR','document',False),
 ('migration','Migration Slip Campus - Campus','MIG','document',False),
 ('rustication','Student Rustication Notice','SRN','document',False),
 ('warning','Student Warning Letter','SWL','document',True),
 ('trip','Student Trip Letter','TRIP','document',True),
 ('fee-clearance','Student Fee Clearance Certificate','FCC','document',True),
 ('admission-confirmation','Student Admission Confirmation Letter','SAC','document',True),
 ('envelope','Student Envelopes Tags','ENV','label',True),
 ('admitted-card','Student Admitted Card','AC','label',True),
 ('birth','Student Birth Certificate','BRC','document',True),
 ('appreciation','Appreciation Certificate','APP','document',True),
]
CATALOG={key:dict(name=name,prefix=prefix,layout=layout,captured=captured) for key,name,prefix,layout,captured in DOCUMENTS}

HEADER='''<table style="width:100%;border-bottom:3px solid #176b4a"><tr><td style="width:20%">[instLogo]</td><td style="width:60%;text-align:center"><h2>[instName]</h2><p>[instAddress]</p><p>[instContact] · [instEmail]</p></td><td style="width:20%;text-align:right">[stdPic]</td></tr></table>'''
FOOTER='''<table style="width:100%;margin-top:45px"><tr><td style="width:35%;text-align:center">____________________<br>ADMIN OFFICER</td><td style="width:30%;text-align:center">OFFICIAL STAMP</td><td style="width:35%;text-align:center">____________________<br>PRINCIPAL</td></tr></table>'''

def default_content(key):
    name=CATALOG[key]['name']
    title=f'<h1 style="text-align:center;color:#176b4a">{name.upper()}</h1>'
    date='<table style="width:100%"><tr><td>Date: [todayDate]</td><td style="text-align:right">Ref: [reference]</td></tr></table>'
    identity='<p><b>[studentName]</b>, son / daughter of <b>[fatherName]</b>, Class <b>[className]</b>, Section <b>[sectionName]</b>.</p>'
    copy='<p>Certificate copy: [copyType]</p>'
    registration='<table style="width:100%"><tr><td>Registration No.: [regNo]</td><td>Date of Birth: [dob]</td><td>Session: [SessionName]</td></tr></table>'
    body={
      'school-leaving':('<h3 style="text-align:center;letter-spacing:1px;margin:14px 0">TO WHOM IT MAY CONCERN</h3>'
        '<p style="text-align:justify;line-height:1.9">This is to certify that <b>[studentName]</b>, son/daughter of <b>[fatherName]</b>, was a duly enrolled student of <b>[instName]</b>. The student attended Class <b>[className]</b>, Section <b>[sectionName]</b>, during Academic Session <b>[SessionName]</b>, as recorded in the institution’s admission register.</p>'
        '<p style="text-align:justify;line-height:1.9">This document is issued upon request as an official record of the student’s enrolment at this institution, for presentation to another educational institution where required. We extend our best wishes for the student’s continued academic progress and future success.</p>'
        '<table class="certificate-record-grid" style="width:100%;border-collapse:collapse;table-layout:fixed;margin:18px 0"><colgroup><col style="width:24%"><col style="width:26%"><col style="width:24%"><col style="width:26%"></colgroup>'
        '<tr><th style="border:1px solid #8ba99a;padding:10px;text-align:left">Registration No.</th><td style="border:1px solid #8ba99a;padding:10px">[regNo]</td><th style="border:1px solid #8ba99a;padding:10px;text-align:left">Date of Birth</th><td style="border:1px solid #8ba99a;padding:10px">[dob]</td></tr>'
        '<tr><th style="border:1px solid #8ba99a;padding:10px;text-align:left">Academic Session</th><td style="border:1px solid #8ba99a;padding:10px">[SessionName]</td><th style="border:1px solid #8ba99a;padding:10px;text-align:left">Date of Leaving</th><td style="border:1px solid #8ba99a;padding:10px">[leavingDate]</td></tr>'
        '<tr><th style="border:1px solid #8ba99a;padding:10px;text-align:left">Admission Class</th><td style="border:1px solid #8ba99a;padding:10px">[admissionClass]</td><th style="border:1px solid #8ba99a;padding:10px;text-align:left">Admission Date</th><td style="border:1px solid #8ba99a;padding:10px">[admissionDate]</td></tr></table>'
        '<h3>Remarks</h3><p>__________________________________________________</p>'+copy),
      'character':identity+'<p>This certificate records the student’s character and conduct during attendance at [instName].</p><p>Character / conduct: ____________________</p>'+registration+copy,
      'migration':identity+'<p>Migration from campus: [campusName]</p><p>Migration to campus: ____________________</p><p>Effective date: ____________________</p><p>Reason / remarks: ________________________________________</p>'+registration+copy,
      'rustication':identity+'<p>This notice records an administrative decision concerning the student’s enrolment.</p><p>Effective date: ____________________</p><p>Reason and supporting record: ______________________________</p><p>Parent / guardian acknowledgement: ________________________</p><p>This document does not change the student’s saved status.</p>'+copy,
      'warning':identity+'<h3>Subject: Attendance and academic progress</h3><p>Dear parent / guardian,</p><p>Please meet the school to discuss the student’s attendance, academic progress and agreed steps for improvement.</p><p>Areas requiring attention: ______________________________</p><p>Meeting date and time: _________________________________</p><p>Review date: _________________________________________</p><p>Sincerely,<br>Principal, [instName]</p>',
      'trip':'<h3>Educational and Recreational School Trip</h3><p>Respected Sir / Madam,</p><p>[instName] requests permission to arrange an educational visit to your venue.</p><p>Venue / destination: ______________________________</p><p>Trip date: ______________________________________</p><table style="width:100%"><tr><td>Total students: __________</td><td>Total staff: __________</td></tr></table><p>Regards,<br>Principal<br>[instName]<br>[instContact]</p>',
      'fee-clearance':identity+'<p>Fee position for the academic session [SessionName], as recorded on [todayDate]:</p><table style="width:100%"><tr><th>Decided Tuition Fee</th><td>[tuitionFee]</td></tr><tr><th>Current Month Payable</th><td>[currPayable]</td></tr><tr><th>Current Month Remaining</th><td>[curRemaining]</td></tr><tr><th>Total Outstanding</th><td>[totalRemPayable]</td></tr></table><p>This clearance is issued against the fee records held by the school.</p>'+copy,
      'admission-confirmation':identity+'<p>Admission at [instName] is recorded from [admissionDate].</p><h3>Basic Fee Plan</h3><table style="width:100%"><tr><th>Admission Fee</th><td>[admissionfee]</td></tr><tr><th>Tuition Fee</th><td>[tuitionFee]</td></tr></table><h3>Current Fee Status</h3><table style="width:100%"><tr><th>Payable</th><td>[currPayable]</td></tr><tr><th>Paid</th><td>[currentPaid]</td></tr><tr><th>Remaining</th><td>[curRemaining]</td></tr></table>'+copy,
      'birth':identity+'<p>Is studying at <b>[instName]</b>.</p>'+registration+'<p>The date of birth above is reproduced from the school’s admission record. This is a school-issued record certificate.</p>'+copy,
      'appreciation':identity+'<h3 style="text-align:center">Awarded for Excellence</h3><p>Has achieved position __________ in ____________________ examination / activity.</p><p>We recognise the student’s effort, participation and progress, and wish them continued success.</p>'+copy,
    }
    if key in ('student-card-new','student-card','guardian-card'):
        front='''<table style="width:100%;background-color:#176b4a;color:#ffffff"><tr><td style="text-align:center">[instLogo]<h3>[instName]</h3>[stdPhoto]<p><b>Student Name:</b> [studentName]</p><p><b>Father Name:</b> [fatherName]</p><p><b>Class:</b> [className] &nbsp; <b>Section:</b> [sectionName]</p><p><b>Roll No.:</b> [rollNo] &nbsp; <b>Student ID:</b> [sid]</p><p>Admission: [admissionDate]</p></td></tr></table>'''
        back='''<table style="width:100%"><tr><td style="text-align:center"><h3>STUDENT CARD</h3><p>Campus: [campusName]</p><p>Contact: [fatherMobile]</p><p>Session: [SessionName]</p>[qrCode]<p>If found, please return to:</p><p>[instName]<br>[instAddress]<br>[instContact]</p></td></tr></table>'''
        if key=='guardian-card':
            front='''<table style="width:100%;height:100%;background-color:#176b4a;color:#ffffff;border-collapse:collapse"><tr><td style="text-align:center;padding:12px">[instLogo]<h3 style="margin:5px 0;color:#ffffff">[instName]</h3><p style="margin:4px 0;color:#ffffff"><b>AUTHORIZED PICK-UP CARD</b></p>[stdPhoto]<p style="margin:8px 0;color:#ffffff"><b>Student:</b> [studentName]</p><p style="margin:5px 0;color:#ffffff"><b>Class:</b> [className] · [sectionName]</p><p style="margin:5px 0;color:#ffffff"><b>Student ID:</b> [sid] · <b>Roll:</b> [rollNo]</p><p style="margin:8px 0;color:#ffffff"><b>Guardian:</b> [fatherName]</p><p style="margin:7px 0;color:#ffffff"><b>Guardian Photo</b></p>[guardianPhoto]</td></tr></table>'''
            back='''<table style="width:100%;height:100%;border-collapse:collapse"><tr><td style="padding:12px;vertical-align:top"><h3 style="text-align:center;margin:4px 0 12px;color:#176b4a">GUARDIAN VERIFICATION</h3><table style="width:100%;border-collapse:collapse"><tr><th style="width:36%;text-align:left;border-bottom:1px solid #a7c8b6;padding:7px 3px">Guardian</th><td style="border-bottom:1px solid #a7c8b6;padding:7px 3px">[fatherName]</td></tr><tr><th style="text-align:left;border-bottom:1px solid #a7c8b6;padding:7px 3px">Contact</th><td style="border-bottom:1px solid #a7c8b6;padding:7px 3px">[fatherMobile]</td></tr><tr><th style="text-align:left;border-bottom:1px solid #a7c8b6;padding:7px 3px">Student</th><td style="border-bottom:1px solid #a7c8b6;padding:7px 3px">[studentName]</td></tr><tr><th style="text-align:left;border-bottom:1px solid #a7c8b6;padding:7px 3px">Valid Until</th><td style="border-bottom:1px solid #a7c8b6;padding:7px 3px">________________</td></tr></table><p style="margin:10px 0 4px"><b>Pick-up instructions</b></p><p style="margin:4px 0">Present this card at the school gate. Staff must verify the authorised adult before releasing the student.</p><p style="margin:8px 0 4px;text-align:center">[qrCode]</p><p style="margin:5px 0;text-align:center"><b>[instName]</b></p><p style="margin:3px 0;text-align:center">[instContact]</p></td></tr></table>'''
        return dict(header='',body='<table style="width:100%;height:86mm"><tr><td style="width:50%;vertical-align:top">'+front+'</td><td style="width:50%;vertical-align:top">'+back+'</td></tr></table>',footer='')
    if key in ('envelope','admitted-card'):
        label='<table style="width:100%"><tr><td>[instLogo]</td><td><b>[instName]</b><br>[instAddress]</td></tr><tr><td colspan="2">SID: [sid] · Roll No.: [rollNo]</td></tr><tr><td colspan="2"><b>[studentName]</b> S/D/O [fatherName]<br>[className] · [sectionName] · [SessionName]</td></tr></table>'
        if key=='admitted-card':label+='<p>Admission Date: [admissionDate]</p><p>Admission Fee: [admissionfee] · Tuition Fee: [tuitionFee]</p><p>Payable: [totalPayable] · Paid: [totalPaidAmount] · Remaining: [curRemaining]</p><p>ACCOUNTANT SIGNATURE __________ PRINCIPAL SIGNATURE __________</p>'
        return dict(header='',body=label,footer='')
    return dict(header=HEADER,body=date+title+body[key],footer=FOOTER)
