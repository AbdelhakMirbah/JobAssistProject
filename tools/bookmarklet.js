javascript:(function(){
  const existingModal = document.getElementById('job-assistant-modal');
  if (existingModal) existingModal.remove();

  // Extract selected text or main content
  const selectedText = window.getSelection().toString().trim();
  const pageTitle = document.title || '';
  const pageUrl = window.location.href;

  // Best-effort auto-extraction
  let detectedTitle = '';
  let detectedCompany = '';

  const h1 = document.querySelector('h1');
  if (h1) detectedTitle = h1.innerText.trim();

  // Common selectors on LinkedIn, WTTJ, Indeed
  const companyEl = document.querySelector('.job-details-jobs-unified-top-card__company-name, [data-company-name="true"], .company-name, header [class*="company"]');
  if (companyEl) detectedCompany = companyEl.innerText.trim();

  // Build clean overlay modal
  const overlay = document.createElement('div');
  overlay.id = 'job-assistant-modal';
  overlay.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    width: 380px;
    background: #0f172a;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
    z-index: 99999999;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
  `;

  overlay.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h3 style="margin:0; font-size:15px; font-weight:700; color:#38bdf8;">⚡ Job Assistant n8n</h3>
      <button id="ja-close" style="background:none; border:none; color:#94a3b8; font-size:18px; cursor:pointer;">&times;</button>
    </div>
    
    <label style="display:block; margin-bottom:4px; font-weight:600; color:#cbd5e1;">Job Title</label>
    <input id="ja-title" value="${detectedTitle.replace(/"/g, '&quot;')}" style="width:100%; box-sizing:border-box; padding:8px 10px; background:#1e293b; border:1px solid #475569; border-radius:6px; color:#fff; margin-bottom:10px;" />

    <label style="display:block; margin-bottom:4px; font-weight:600; color:#cbd5e1;">Company Name</label>
    <input id="ja-company" value="${detectedCompany.replace(/"/g, '&quot;')}" style="width:100%; box-sizing:border-box; padding:8px 10px; background:#1e293b; border:1px solid #475569; border-radius:6px; color:#fff; margin-bottom:10px;" />

    <label style="display:block; margin-bottom:4px; font-weight:600; color:#cbd5e1;">Location</label>
    <input id="ja-location" value="Paris, France" style="width:100%; box-sizing:border-box; padding:8px 10px; background:#1e293b; border:1px solid #475569; border-radius:6px; color:#fff; margin-bottom:10px;" />

    <label style="display:block; margin-bottom:4px; font-weight:600; color:#cbd5e1;">Job Description</label>
    <textarea id="ja-desc" rows="4" style="width:100%; box-sizing:border-box; padding:8px 10px; background:#1e293b; border:1px solid #475569; border-radius:6px; color:#fff; margin-bottom:14px; font-size:11px;">${(selectedText || document.body.innerText.substring(0, 3000)).replace(/</g, '&lt;')}</textarea>

    <button id="ja-submit" style="width:100%; padding:10px; background:#2563eb; color:#fff; border:none; border-radius:6px; font-weight:600; cursor:pointer; font-size:14px;">🚀 Tailor & Send to Telegram</button>
    <div id="ja-status" style="margin-top:10px; text-align:center; font-size:12px; color:#94a3b8;"></div>
  `;

  document.body.appendChild(overlay);

  document.getElementById('ja-close').onclick = () => overlay.remove();

  document.getElementById('ja-submit').onclick = async () => {
    const btn = document.getElementById('ja-submit');
    const status = document.getElementById('ja-status');
    btn.disabled = true;
    btn.innerText = '⏳ Processing with Gemini...';
    status.innerText = 'Sending to local n8n workflow...';

    const payload = {
      job_title: document.getElementById('ja-title').value || pageTitle,
      company_name: document.getElementById('ja-company').value || 'Hiring Company',
      company_location: document.getElementById('ja-location').value || 'Remote / France',
      job_description: document.getElementById('ja-desc').value,
      job_url: pageUrl
    };

    try {
      const response = await fetch('http://localhost:5678/webhook/job-apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (response.ok) {
        btn.style.background = '#16a34a';
        btn.innerText = '✅ Sent!';
        status.innerHTML = '<span style="color:#4ade80;">Success! Check your Telegram for PDFs & Approve button.</span>';
        setTimeout(() => overlay.remove(), 4000);
      } else {
        throw new Error('HTTP ' + response.status);
      }
    } catch (err) {
      btn.disabled = false;
      btn.innerText = '❌ Retry';
      btn.style.background = '#dc2626';
      status.innerHTML = `<span style="color:#f87171;">Error: ${err.message}. Is n8n running on port 5678?</span>`;
    }
  };
})();
