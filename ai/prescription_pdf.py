import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

class MedicalPDFGenerator:
    """
    Generates a professional hospital prescription PDF using ReportLab.
    Ensures strict line-by-line formatting, no hallucinated medicines, and clear 'Not specified' markers.
    """
    def generate(self, prescription_data: dict, filepath: str) -> bool:
        """
        Generates a prescription PDF based on structured data.
        Returns True if successful, False otherwise.
        """
        try:
            # Create document template with 0.5-inch margins
            doc = SimpleDocTemplate(
                filepath,
                pagesize=letter,
                rightMargin=36,
                leftMargin=36,
                topMargin=36,
                bottomMargin=36
            )
            
            story = []
            
            styles = getSampleStyleSheet()
            
            primary_color = colors.HexColor("#007BFF")
            text_dark = colors.HexColor("#333333")
            text_muted = colors.HexColor("#666666")
            
            hospital_sub_style = ParagraphStyle(
                'HospitalSub',
                parent=styles['Normal'],
                textColor=text_muted,
                fontSize=9,
                leading=12
            )
            
            doc_info_style = ParagraphStyle(
                'DocInfo',
                parent=styles['Normal'],
                textColor=text_dark,
                fontSize=10,
                leading=14,
                alignment=2 # Right
            )
            
            section_title_style = ParagraphStyle(
                'SectionTitle',
                parent=styles['Heading2'],
                textColor=primary_color,
                fontSize=12,
                leading=16,
                spaceBefore=6,
                spaceAfter=4
            )
            
            body_style = ParagraphStyle(
                'BodyTextCustom',
                parent=styles['Normal'],
                textColor=text_dark,
                fontSize=10,
                leading=14
            )
            
            table_header_style = ParagraphStyle(
                'TableHeader',
                parent=styles['Normal'],
                textColor=colors.whitesmoke,
                fontSize=10,
                leading=12,
                fontName="Helvetica-Bold"
            )
            
            # 1. Hospital Header Section
            hospital_details = "123 Healthcare Boulevard, Medical District<br/>Phone: +1 (555) 019-2834 | Email: contact@metrohospital.com"
            
            doc_name = prescription_data.get('doctor_name', 'Dr. Medical Specialist')
            doc_credentials = f"<b>{doc_name}</b>, {prescription_data.get('specialization', 'Dermatology')}"
            doc_license = f"Reg No: {prescription_data.get('license_number', 'MD-1003')}"
            
            header_left = Paragraph(f"<font color='#007BFF' size='16'><b>✙ METROPOLITAN GENERAL HOSPITAL</b></font><br/><br/>{hospital_details}", hospital_sub_style)
            header_right = Paragraph(f"{doc_credentials}<br/><font color='#666666'>{doc_license}</font>", doc_info_style)
            
            header_table = Table([[header_left, header_right]], colWidths=[320, 220])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 10),
            ]))
            story.append(header_table)
            
            # Divider line
            story.append(Table([[""]], colWidths=[540], rowHeights=[2], style=TableStyle([
                ('LINEBELOW', (0,0), (-1,-1), 2, primary_color),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ])))
            story.append(Spacer(1, 10))
            
            # 2. Patient Profile Banner
            patient_name = prescription_data.get('patient_name') or 'Not specified'
            patient_age = str(prescription_data.get('age')) if prescription_data.get('age') else 'Not specified'
            patient_gender = prescription_data.get('gender') or 'Not specified'
            patient_phone = prescription_data.get('patient_phone') or 'Not specified'
            appointment_date = prescription_data.get('appointment_date') or 'Not specified'
            
            patient_info_html = f"""
            <b>Patient Name:</b> {patient_name} &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <b>Age/Gender:</b> {patient_age} yrs / {patient_gender}<br/>
            <b>Phone:</b> {patient_phone} &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <b>Date:</b> {appointment_date}
            """
            
            patient_info_p = Paragraph(patient_info_html, body_style)
            patient_table = Table([[patient_info_p]], colWidths=[540])
            patient_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F0F8FF")),
                ('TOPPADDING', (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ('LEFTPADDING', (0,0), (-1,-1), 12),
                ('RIGHTPADDING', (0,0), (-1,-1), 12),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#D0E4F7")),
            ]))
            story.append(patient_table)
            story.append(Spacer(1, 15))
            
            # 3. Symptoms & Diagnosis
            symptoms = prescription_data.get('symptoms', [])
            if isinstance(symptoms, list):
                symptoms_str = ", ".join(symptoms) if len(symptoms) > 0 else "Not specified"
            else:
                symptoms_str = symptoms or "Not specified"
                
            diagnosis = prescription_data.get('diagnosis') or 'Not specified'
            
            clinical_info_html = f"""
            <b>Presented Symptoms:</b> {symptoms_str}<br/>
            <b>Diagnosis:</b> {diagnosis}
            """
            story.append(Paragraph("CLINICAL CASE SUMMARY", section_title_style))
            story.append(Paragraph(clinical_info_html, body_style))
            story.append(Spacer(1, 12))
            
            # 4. Medicines Table
            story.append(Paragraph("Rx (MEDICATIONS)", section_title_style))
            
            medicines_rows = [[
                Paragraph("<b>Medicine Name</b>", table_header_style),
                Paragraph("<b>Dosage</b>", table_header_style),
                Paragraph("<b>Frequency / Timing</b>", table_header_style),
                Paragraph("<b>Duration</b>", table_header_style)
            ]]
            
            medicines_list = prescription_data.get('medicines', [])
            if not medicines_list:
                medicines_rows.append([
                    Paragraph("No medications explicitly prescribed", body_style),
                    Paragraph("Not specified", body_style),
                    Paragraph("Not specified", body_style),
                    Paragraph("Not specified", body_style)
                ])
            else:
                for med in medicines_list:
                    med_name = med.get('name') or 'Not specified'
                    dosage = med.get('dosage') or 'Not specified'
                    frequency = med.get('frequency') or 'Not specified'
                    duration = med.get('duration') or 'Not specified'
                    
                    medicines_rows.append([
                        Paragraph(med_name, body_style),
                        Paragraph(dosage, body_style),
                        Paragraph(frequency, body_style),
                        Paragraph(duration, body_style)
                    ])
                    
            med_table = Table(medicines_rows, colWidths=[180, 110, 150, 100])
            med_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), primary_color),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#F5F9FD")]),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#D0E4F7")),
                ('TOPPADDING', (0,0), (-1,-1), 6),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ('LEFTPADDING', (0,0), (-1,-1), 8),
            ]))
            story.append(med_table)
            story.append(Spacer(1, 15))
            
            # 5. Tests Recommended & Treatment Plan / Doctor Advice Line-by-Line
            recommended_tests = prescription_data.get('recommended_tests', [])
            if isinstance(recommended_tests, list):
                tests_str = ", ".join(recommended_tests) if len(recommended_tests) > 0 else "None"
            else:
                tests_str = recommended_tests or "None"
            
            treatment_plan = prescription_data.get('treatment_plan') or 'Not specified'
            doctor_advice = prescription_data.get('doctor_advice') or 'Not specified'
            follow_up_date = prescription_data.get('follow_up_date') or 'Not specified'
            
            doctor_advice_formatted = doctor_advice.replace('\n', '<br/>')
            treatment_plan_formatted = treatment_plan.replace('\n', '<br/>')
            
            advice_html = f"""
            <b>Dietary / Behavioral Advice:</b><br/>{doctor_advice_formatted}<br/><br/>
            <b>Treatment Instruction:</b><br/>{treatment_plan_formatted}
            """
            
            secondary_column_data = []
            if tests_str and tests_str.lower() != 'none':
                secondary_column_data.append(Paragraph("RECOMMENDED INVESTIGATIONS", section_title_style))
                secondary_column_data.append(Paragraph(f"<b>Suggested Lab Tests:</b> {tests_str}", body_style))
                secondary_column_data.append(Spacer(1, 8))
                
            secondary_column_data.append(Paragraph("PLAN & ADVICE", section_title_style))
            secondary_column_data.append(Paragraph(advice_html, body_style))
            secondary_column_data.append(Spacer(1, 8))
            secondary_column_data.append(Paragraph(f"<b>Follow-up Visit Date:</b> <font color='#007BFF'><b>{follow_up_date}</b></font>", body_style))
            
            for item in secondary_column_data:
                story.append(item)
                
            story.append(Spacer(1, 30))
            
            # 6. Doctor Signature Block
            sig_text = f"""
            <br/><br/>
            _____________________________<br/>
            <b>{doc_credentials}</b><br/>
            {doc_license}
            """
            sig_p = Paragraph(sig_text, doc_info_style)
            sig_table = Table([[Spacer(1,1), sig_p]], colWidths=[300, 240])
            sig_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
            ]))
            story.append(sig_table)
            
            doc.build(story)
            return True
        except Exception as e:
            print(f"Error compiling PDF: {e}")
            return False
