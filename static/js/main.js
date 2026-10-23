// Medical System Javascript Controller - main.js

document.addEventListener('DOMContentLoaded', function() {
    
    // Auto-dismiss Bootstrap flash alerts after 5 seconds
    setTimeout(function() {
        let alerts = document.querySelectorAll('.alert-dismissible');
        alerts.forEach(function(alert) {
            let bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);

    // Dynamic Slot Selection logic (Patient Booking)
    const slotContainer = document.getElementById('slots-container');
    if (slotContainer) {
        slotContainer.addEventListener('click', function(e) {
            const slotOpt = e.target.closest('.slot-option');
            if (slotOpt && !slotOpt.classList.contains('disabled')) {
                // Clear active selected
                document.querySelectorAll('.slot-option').forEach(el => el.classList.remove('selected'));
                // Select clicked
                slotOpt.classList.add('selected');
                // Update hidden input
                const slotInput = document.getElementById('selected_slot_id');
                if (slotInput) {
                    slotInput.value = slotOpt.dataset.slotId;
                }
            }
        });
    }

    // Dynamic Availability / Date changes in Appointment Booking
    const dateInput = document.getElementById('appointment_date');
    const doctorSelect = document.getElementById('doctor_id');
    if (dateInput && doctorSelect) {
        const fetchAndRenderSlots = () => {
            const docId = doctorSelect.value;
            const dateVal = dateInput.value;
            if (!docId || !dateVal) return;

            // Show loading state
            if (slotContainer) {
                slotContainer.innerHTML = '<div class="text-center w-100 py-3"><div class="spinner-border text-primary" role="status"></div><p class="mt-2 text-muted">Loading 20-minute slots...</p></div>';
            }
            // Clear any previously selected slot since the list is being refreshed
            const slotInput = document.getElementById('selected_slot_id');
            if (slotInput) slotInput.value = '';

            fetch(`/api/slots?doctor_id=${docId}&date=${dateVal}`)
                .then(res => res.json())
                .then(data => {
                    const dayName = data.day || 'this day';

                    if (data.success && data.unavailable_day) {
                        // Doctor has not configured any working hours for this day at all
                        slotContainer.innerHTML = `
                            <div class="alert alert-secondary text-center w-100 mb-0">
                                <i class="fa fa-calendar-xmark mb-2 d-block fa-2x"></i>
                                <strong>Doctor is not available on ${dayName}s</strong><br>
                                <span class="small">Please choose a different date.</span>
                            </div>`;
                    } else if (data.success && data.slots.length > 0) {
                        const shiftLabel = data.shift_label || '';

                        let html = `
                            <div class="d-flex align-items-center gap-2 mb-3 px-1">
                                <span class="badge bg-primary-subtle text-primary px-3 py-2 rounded-pill">
                                    <i class="fa fa-calendar-day me-1"></i>
                                    ${dayName} &nbsp;·&nbsp; ${shiftLabel}
                                </span>
                                <span class="text-muted small">${data.slots.length} slot(s) available</span>
                            </div>
                            <div class="slot-grid">`;

                        data.slots.forEach(slot => {
                            // All returned slots are 'available' — no disabled class needed
                            html += `
                                <div class="slot-option" data-slot-id="${slot.id}">
                                    <i class="fa fa-clock me-1 text-primary small"></i>
                                    ${slot.start_time.substring(0, 5)} &ndash; ${slot.end_time.substring(0, 5)}
                                </div>
                            `;
                        });
                        html += '</div>';
                        slotContainer.innerHTML = html;
                    } else if (data.success && data.slots.length === 0) {
                        const shiftInfo = data.shift_label || '';
                        slotContainer.innerHTML = `
                            <div class="alert alert-warning text-center w-100 mb-0">
                                <i class="fa fa-calendar-times mb-2 d-block fa-2x"></i>
                                <strong>No available slots for ${dayName}</strong><br>
                                <span class="small">${shiftInfo ? 'Working hours: ' + shiftInfo + '. All 20-minute slots are already booked.' : 'All 20-minute slots are fully booked for this date.'}</span>
                            </div>`;
                    } else {
                        slotContainer.innerHTML = '<div class="alert alert-danger text-center w-100">Failed to load slots. Please try again.</div>';
                    }
                })
                .catch(err => {
                    console.error("Error retrieving slots:", err);
                    slotContainer.innerHTML = '<div class="alert alert-danger text-center w-100">Failed to load available slots.</div>';
                });
        };

        dateInput.addEventListener('change', fetchAndRenderSlots);
        doctorSelect.addEventListener('change', fetchAndRenderSlots);

        // Guard against submitting the booking form without an actual slot selected
        const bookingForm = doctorSelect.closest('form');
        if (bookingForm) {
            bookingForm.addEventListener('submit', function(e) {
                const slotInput = document.getElementById('selected_slot_id');
                if (!slotInput || !slotInput.value) {
                    e.preventDefault();
                    alert('This slot is already booked or too close to another appointment. Please choose another available slot.');
                }
            });
        }
    }


    // Dynamic Medicine Table Rows in Prescription editing sheet
    const addMedRowBtn = document.getElementById('add-medicine-row');
    const medicineTable = document.getElementById('medicines-entry-table');
    if (addMedRowBtn && medicineTable) {
        addMedRowBtn.addEventListener('click', function() {
            const tbody = medicineTable.querySelector('tbody');
            const rowCount = tbody.querySelectorAll('tr').length;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><input type="text" name="medicines[${rowCount}][name]" class="form-control form-control-custom" placeholder="e.g. Paracetamol" required></td>
                <td><input type="text" name="medicines[${rowCount}][dosage]" class="form-control form-control-custom" placeholder="e.g. 650mg" required></td>
                <td><input type="text" name="medicines[${rowCount}][frequency]" class="form-control form-control-custom" placeholder="e.g. Twice Daily" required></td>
                <td><input type="text" name="medicines[${rowCount}][duration]" class="form-control form-control-custom" placeholder="e.g. 5 Days" required></td>
                <td class="text-center"><button type="button" class="btn btn-outline-danger btn-sm remove-row-btn"><i class="fa fa-trash"></i></button></td>
            `;
            tbody.appendChild(tr);
        });

        medicineTable.addEventListener('click', function(e) {
            const removeBtn = e.target.closest('.remove-row-btn');
            if (removeBtn) {
                const row = removeBtn.closest('tr');
                row.remove();
                
                // Re-index remaining input rows
                const tbody = medicineTable.querySelector('tbody');
                tbody.querySelectorAll('tr').forEach((r, idx) => {
                    r.querySelectorAll('input').forEach(input => {
                        const nameAttr = input.name;
                        // Replace [number] with [idx]
                        input.name = nameAttr.replace(/\[\d+\]/, `[${idx}]`);
                    });
                });
            }
        });
    }
});
