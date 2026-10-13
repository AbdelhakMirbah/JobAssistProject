import fs from 'fs';
import path from 'path';
import dotenv from 'dotenv';
import puppeteer from 'puppeteer';
import { scrapeJobs } from 'ts-jobspy';
import { renderCvHtml, renderCoverLetterHtml } from '../scripts/render_html.js';

dotenv.config();

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;
const FIREBASE_DB_URL = process.env.FIREBASE_DATABASE_URL;

const PROCESSED_JOBS_FILE = path.resolve(process.cwd(), 'data/processed_jobs.json');
const PROFILE_FILE = path.resolve(process.cwd(), 'data/master_profile.json');

// ─── AI Engine Configuration (Gemini Cloud or Local Ollama) ────────────────
const AI_PROVIDER = process.env.AI_PROVIDER || 'gemini'; // 'gemini' | 'ollama'
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-3-flash-preview';
const OLLAMA_HOST = process.env.OLLAMA_HOST || 'http://localhost:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'mistral';

function loadProcessedJobs() {
  if (fs.existsSync(PROCESSED_JOBS_FILE)) {
    try { return JSON.parse(fs.readFileSync(PROCESSED_JOBS_FILE, 'utf8')); }
    catch { return {}; }
  }
  return {};
}

function saveProcessedJobs(data) {
  fs.writeFileSync(PROCESSED_JOBS_FILE, JSON.stringify(data, null, 2), 'utf8');
}

/**
 * Fetches targeted tech jobs using ts-jobspy (Indeed / LinkedIn scraper)
 * with automatic fallback to public APIs (Arbeitnow).
 */
export async function fetchTargetTechJobs() {
  const targetLocation = process.env.JOB_LOCATION || 'Morocco';
  const targetCountry = (process.env.JOB_COUNTRY || 'morocco').toLowerCase();
  const customTerms = process.env.JOB_SEARCH_TERMS
    ? process.env.JOB_SEARCH_TERMS.split(',').map(s => s.trim())
    : [
        'Junior Software Engineer',
        'Software Engineer',
        'Junior Data Engineer',
        'Data Engineer',
        'Développeur Full Stack',
        'Développeur Mobile'
      ];

  const excludeKeywords = [
    'lead', 'principal', 'head of', 'director', 'vp ', 'cto', 'architect',
    'sales', 'marketing', 'recruiter', 'hr ', 'stage', 'internship', 'stagiaire'
  ];

  const allJobs = [];
  const seenUrls = new Set();

  console.log(`🌐 Scraping targeted offers via JobSpy (Location: ${targetLocation}, Country: ${targetCountry})...`);

  for (const term of customTerms) {
    try {
      console.log(`   🔍 Searching: "${term}"...`);
      const res = await scrapeJobs({
        sites: ['indeed'],
        searchTerm: term,
        location: targetLocation,
        country: targetCountry,
        resultsWanted: 5,
        verbose: 0
      });

      for (const job of (res.jobs || [])) {
        if (!job.title || !job.jobUrl) continue;
        if (seenUrls.has(job.jobUrl)) continue;

        const titleLower = job.title.toLowerCase();
        // Skip explicitly senior / non-matching roles
        if (excludeKeywords.some(kw => titleLower.includes(kw))) continue;

        seenUrls.add(job.jobUrl);
        allJobs.push({
          id: `job_${(job.id || job.jobUrl).replace(/[^a-zA-Z0-9_-]/g, '_').slice(-40)}`,
          source: job.site ? `JobSpy:${job.site}` : 'JobSpy',
          job_title: job.title,
          company_name: job.company || 'Entreprise Confidentielle',
          company_location: job.location || targetLocation,
          job_url: job.jobUrl,
          job_description: (job.description || '')
            .replace(/<[^>]+>/g, ' ')
            .replace(/\s+/g, ' ')
            .trim()
        });
      }
    } catch (err) {
      console.warn(`   ⚠️ JobSpy query "${term}" notice:`, err.message);
    }
  }

  // Fallback to Arbeitnow API if JobSpy returned no jobs
  if (allJobs.length === 0) {
    console.log('   ⚠️ JobSpy returned 0 jobs, falling back to public board...');
    try {
      const res = await fetch('https://www.arbeitnow.com/api/job-board-api');
      if (res.ok) {
        const data = await res.json();
        const items = data.data || [];
        const fallbackTarget = ['data', 'software', 'python', 'developer', 'engineer', 'web', 'mobile'];
        for (const job of items) {
          const title = (job.title || '').toLowerCase();
          if (excludeKeywords.some(kw => title.includes(kw))) continue;
          if (!fallbackTarget.some(kw => title.includes(kw))) continue;
          allJobs.push({
            id: `job_${job.slug}`,
            source: 'TechBoard',
            job_title: job.title,
            company_name: job.company_name,
            company_location: job.remote ? `${job.location} (Remote)` : job.location,
            job_url: job.url,
            job_description: (job.description || '')
              .replace(/<[^>]+>/g, ' ')
              .replace(/\s+/g, ' ')
              .trim()
          });
        }
      }
    } catch (err) {
      console.error('❌ Fallback scraper error:', err.message);
    }
  }

  console.log(`📋 Found ${allJobs.length} matching software & data job postings.`);
  return allJobs;
}

/**
 * Calls Gemini API directly with the chosen efficient model.
 * Retries up to 3 times with exponential backoff on temporary rate limits (429/503).
 */
async function callGemini(prompt) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`;
  const maxAttempts = 3;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: {
            responseMimeType: 'application/json',
            temperature: 0.25
          }
        })
      });

      if (res.ok) {
        const data = await res.json();

        // Detect empty candidates array (model refused / safety block / recitation)
        if (!data.candidates || data.candidates.length === 0) {
          const blockReason = data.promptFeedback?.blockReason || 'UNKNOWN';
          throw new Error(`Gemini returned no candidates (blockReason: ${blockReason})`);
        }

        const candidate = data.candidates[0];
        const finishReason = candidate.finishReason || 'UNKNOWN';

        // Treat SAFETY / RECITATION / OTHER finish reasons as non-retryable failures
        if (finishReason !== 'STOP' && finishReason !== 'MAX_TOKENS') {
          throw new Error(`Gemini blocked output (finishReason: ${finishReason})`);
        }

        const text = candidate.content?.parts?.[0]?.text;
        if (!text || text.trim() === '') {
          throw new Error(`Gemini returned empty text (finishReason: ${finishReason})`);
        }

        // Strip markdown code fences if model ignored responseMimeType
        const cleaned = text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim();
        return JSON.parse(cleaned);
      }

      if (res.status === 429 || res.status === 503) {
        if (attempt === maxAttempts) {
          throw new Error(`Gemini rate limit exceeded (HTTP ${res.status}) after ${maxAttempts} attempts`);
        }
        const waitMs = attempt * 5000;
        console.log(`   ⏳ Gemini busy (HTTP ${res.status}), waiting ${waitMs / 1000}s (attempt ${attempt}/${maxAttempts})...`);
        await new Promise(r => setTimeout(r, waitMs));
        continue;
      }

      const body = await res.text();
      throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);

    } catch (err) {
      // Non-retryable errors (blocked, empty, JSON parse fail) — re-throw immediately
      const isNonRetryable = err.message.includes('blockReason') ||
        err.message.includes('finishReason') ||
        err.message.includes('empty text') ||
        err.message.includes('SyntaxError');

      if (isNonRetryable || attempt >= maxAttempts) {
        throw new Error(`Gemini failed: ${err.message}`);
      }

      console.log(`   ⚠️ Gemini attempt ${attempt} failed (${err.message}), retrying in 3s...`);
      await new Promise(r => setTimeout(r, 3000));
    }
  }
  throw new Error('Gemini API returned no response');
}

/**
 * Calls local Ollama running Mistral 7B (or another local model).
 */
async function callOllama(prompt) {
  const res = await fetch(`${OLLAMA_HOST}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: OLLAMA_MODEL,
      prompt,
      format: 'json',
      stream: false
    })
  });
  if (!res.ok) throw new Error(`Ollama HTTP ${res.status}: ${await res.text()}`);
  const data = await res.json();
  const text = data.response;
  if (!text) throw new Error('Empty response body from Ollama');
  return JSON.parse(text);
}

/**
 * Universal AI Caller: Uses Gemini or local Ollama depending on AI_PROVIDER.
 * Automatically falls back to local Ollama if Gemini encounters rate limits or errors.
 */
async function callAi(prompt) {
  if (AI_PROVIDER === 'ollama') {
    return await callOllama(prompt);
  }

  // Primary: Gemini
  try {
    return await callGemini(prompt);
  } catch (geminiErr) {
    console.warn(`   ⚠️ Gemini failed (${geminiErr.message}). Falling back to local Ollama (${OLLAMA_MODEL})...`);
    return await callOllama(prompt);
  }
}

/**
 * Scores job fit and tailors CV + Cover Letter with AI (Gemini or Ollama).
 */
async function tailorJob(job, profile) {
  console.log(`\n🤖 [AI:${AI_PROVIDER}] Analyzing "${job.job_title}" @ "${job.company_name}"...`);

  // Detect language from job description to write the letter in the right language
  const descLower = job.job_description.toLowerCase();
  const isFrench = descLower.includes('nous recherchons') ||
    descLower.includes('rejoindre') ||
    descLower.includes('votre profil') ||
    descLower.includes('expérience') ||
    descLower.includes('poste');

  const prompt = `You are an elite ATS recruitment expert and CV writing specialist.

Evaluate this job posting against the candidate's real profile (Abdelhak Mirbah — Junior Software / Data Engineer).

RULES (strictly follow all):
1. fit_score: 0-100 based ONLY on candidate's real skills. Be honest, don't inflate.
2. tailored_summary: 2-3 tight, punchy sentences. No buzzwords. Match the role language.
3. tailored_experience: Pick the MOST RELEVANT experiences (max 3) with 2-3 crisp, impact-focused bullets each.
   - Each entry MUST include: "title", "company", "location", "start_date", "end_date", "bullets" array.
4. tailored_projects: Pick the MOST RELEVANT projects (max 2) with: "name", "tech_stack" array, "date", "description" string.
5. cover_letter: Write in ${isFrench ? 'FRENCH' : 'ENGLISH'} (match the job language). Exactly 3 natural paragraphs. No templates, sound human.
6. Return ONLY valid JSON matching the schema. No extra text.

JOB POSTING:
Title: ${job.job_title}
Company: ${job.company_name}
Location: ${job.company_location}
Description:
${job.job_description.substring(0, 3500)}

CANDIDATE PROFILE:
${JSON.stringify(profile, null, 2)}

REQUIRED JSON SCHEMA:
{
  "fit_score": 75,
  "match_summary": "Two honest sentences on why this is/isn't a good match.",
  "matched_keywords": ["Python", "SQL", "Docker"],
  "missing_keywords": ["Kubernetes"],
  "target_headline": "Junior Data Engineer | Software Engineer",
  "tailored_summary": "2-3 sentence punchy professional summary for this exact role.",
  "tailored_experience": [
    {
      "title": "Exact role title (keep original, no slash splitting)",
      "company": "Company Name",
      "location": "City, Country",
      "start_date": "Mars 2026",
      "end_date": "Sept. 2026",
      "bullets": ["Measurable achievement with specific tech used."]
    }
  ],
  "tailored_projects": [
    {
      "name": "Project Name",
      "tech_stack": ["Tech1", "Tech2"],
      "date": "Dec. 2025",
      "description": "One sentence describing the project and its impact."
    }
  ],
  "cover_letter": {
    "salutation": "Madame, Monsieur,",
    "paragraphs": [
      "Paragraph 1: Why this company and role specifically.",
      "Paragraph 2: Key achievements directly relevant to their needs.",
      "Paragraph 3: Eagerness to contribute and meet to discuss."
    ],
    "complimentary_close": "Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées."
  }
}`;

  return await callAi(prompt);
}

/**
 * Renders strict 1-page PDF for CV and 1-page PDF for cover letter using Puppeteer.
 */
async function renderPdfs(profile, aiData, job, browser) {
  const safeCompany = job.company_name.replace(/[^a-zA-Z0-9]/g, '_').replace(/__+/g, '_');
  const outputDir = path.resolve(process.cwd(), 'output');
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  const cvHtml = renderCvHtml(profile, {
    tailored_summary: aiData.tailored_summary,
    target_headline: aiData.target_headline,
    experience: aiData.tailored_experience,
    projects: aiData.tailored_projects
  });

  const letterHtml = renderCoverLetterHtml(profile, {
    company_name: job.company_name,
    job_title: job.job_title,
    company_location: job.company_location,
    target_headline: aiData.target_headline,
    salutation: aiData.cover_letter?.salutation,
    cover_letter_paragraphs: aiData.cover_letter?.paragraphs,
    complimentary_close: aiData.cover_letter?.complimentary_close
  });

  const cvPdfPath = path.join(outputDir, `CV_${safeCompany}.pdf`);
  const letterPdfPath = path.join(outputDir, `Lettre_${safeCompany}.pdf`);

  // CV PDF
  const pageCv = await browser.newPage();
  await pageCv.setContent(cvHtml, { waitUntil: 'domcontentloaded' });
  await pageCv.pdf({
    path: cvPdfPath,
    format: 'A4',
    printBackground: true,
    margin: { top: '0mm', right: '0mm', bottom: '0mm', left: '0mm' }
  });
  await pageCv.close();

  // Cover Letter PDF
  const pageLetter = await browser.newPage();
  await pageLetter.setContent(letterHtml, { waitUntil: 'domcontentloaded' });
  await pageLetter.pdf({
    path: letterPdfPath,
    format: 'A4',
    printBackground: true,
    margin: { top: '0mm', right: '0mm', bottom: '0mm', left: '0mm' }
  });
  await pageLetter.close();

  return { cvPdfPath, letterPdfPath };
}

/**
 * Sends a Telegram notification with inline keyboard + both PDF attachments.
 */
async function sendTelegramAlert(job, aiData, cvPdfPath, letterPdfPath) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) {
    console.warn('   ⚠️ Telegram not configured, skipping notification.');
    return;
  }

  const scoreEmoji = aiData.fit_score >= 80 ? '🔥' : aiData.fit_score >= 65 ? '✅' : '🟡';
  const missingStr = (aiData.missing_keywords || []).slice(0, 3).join(', ') || 'None';

  const caption =
    `🎯 *Nouvelle Offre Détectée !*\n\n` +
    `🏢 *Entreprise :* ${job.company_name}\n` +
    `💼 *Poste :* ${job.job_title}\n` +
    `📍 *Lieu :* ${job.company_location}\n` +
    `📊 *Score d'Adéquation :* *${aiData.fit_score}%* ${scoreEmoji}\n\n` +
    `💡 *Synthèse :* ${aiData.match_summary}\n\n` +
    `✅ *Points Forts :* ${(aiData.matched_keywords || []).slice(0, 5).join(', ')}\n` +
    `⚠️ *Manquants :* ${missingStr}`;

  const inlineKeyboard = {
    inline_keyboard: [[
      { text: '🔗 Voir l\'Offre', url: job.job_url },
      { text: '✅ Postulé', callback_data: `APPLY:${job.id}` }
    ]]
  };

  // 1. Send summary message
  await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: TELEGRAM_CHAT_ID,
      text: caption,
      parse_mode: 'Markdown',
      reply_markup: inlineKeyboard
    })
  });

  // 2. Send CV PDF
  const cvBuffer = fs.readFileSync(cvPdfPath);
  const formDataCv = new FormData();
  formDataCv.append('chat_id', TELEGRAM_CHAT_ID);
  formDataCv.append('caption', `📄 CV Adapté — ${job.job_title} @ ${job.company_name}`);
  formDataCv.append('document', new Blob([cvBuffer], { type: 'application/pdf' }), path.basename(cvPdfPath));
  await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument`, {
    method: 'POST',
    body: formDataCv
  });

  // 3. Send Cover Letter PDF
  const letterBuffer = fs.readFileSync(letterPdfPath);
  const formDataLetter = new FormData();
  formDataLetter.append('chat_id', TELEGRAM_CHAT_ID);
  formDataLetter.append('caption', `✉️ Lettre de Motivation — ${job.job_title} @ ${job.company_name}`);
  formDataLetter.append('document', new Blob([letterBuffer], { type: 'application/pdf' }), path.basename(letterPdfPath));
  await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument`, {
    method: 'POST',
    body: formDataLetter
  });
}

/**
 * Saves the processed application record to Firebase Realtime DB.
 */
async function saveToFirebase(job, aiData) {
  if (!FIREBASE_DB_URL) return;
  try {
    const cleanId = job.id.replace(/[^a-zA-Z0-9_-]/g, '_');
    await fetch(`${FIREBASE_DB_URL}/applications/${cleanId}.json`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: job.id,
        job_title: job.job_title,
        company_name: job.company_name,
        location: job.company_location,
        job_url: job.job_url,
        fit_score: aiData.fit_score,
        match_summary: aiData.match_summary,
        matched_keywords: aiData.matched_keywords || [],
        missing_keywords: aiData.missing_keywords || [],
        status: 'PENDING_REVIEW',
        created_at: new Date().toISOString()
      })
    });
    console.log(`   💾 Saved to Firebase!`);
  } catch (err) {
    console.warn(`   ⚠️ Firebase save failed:`, err.message);
  }
}

/**
 * Main pipeline: Fetch → Score → Tailor → PDF → Telegram → Firebase
 *
 * @param {Object} options
 * @param {number} options.maxJobs    Max jobs to fully process per run (default: 3)
 * @param {number} options.minScore   Minimum fit score to generate PDFs (default: 60)
 */
export async function scrapeAndProcessJobs(options = {}) {
  const maxJobs = options.maxJobs ?? 3;
  const minScore = options.minScore ?? 60;

  const activeModel = AI_PROVIDER === 'ollama' ? OLLAMA_MODEL : GEMINI_MODEL;
  console.log(`🚀 Starting Job Assistant (target: ${maxJobs} jobs, threshold: ${minScore}%)`);
  console.log(`   AI Engine : ${AI_PROVIDER.toUpperCase()} (${activeModel})\n`);

  if (AI_PROVIDER === 'gemini' && !GEMINI_API_KEY) {
    console.error('❌ GEMINI_API_KEY not set in .env. Aborting.');
    process.exit(1);
  }

  const profile = JSON.parse(fs.readFileSync(PROFILE_FILE, 'utf8'));
  const processed = loadProcessedJobs();

  const jobs = await fetchTargetTechJobs();
  const newJobs = jobs.filter(j => !processed[j.id]);
  console.log(`✨ ${newJobs.length} unprocessed jobs available.\n`);

  if (newJobs.length === 0) {
    console.log('✅ All jobs already processed. Nothing new today.');
    return;
  }

  // Launch Puppeteer once and reuse across all jobs for efficiency
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });

  let successCount = 0;

  for (const job of newJobs) {
    if (successCount >= maxJobs) break;

    try {
      // Step 1 — AI scoring & tailoring
      const aiData = await tailorJob(job, profile);
      const score = aiData.fit_score ?? 0;
      console.log(`   📊 Fit Score: ${score}%`);

      // Always record the job as processed (even if below threshold)
      processed[job.id] = {
        title: job.job_title,
        company: job.company_name,
        fit_score: score,
        processed_at: new Date().toISOString()
      };
      saveProcessedJobs(processed);

      if (score < minScore) {
        console.log(`   ⚠️ Score (${score}%) < ${minScore}%. Skipped.\n`);
        continue;
      }

      // Step 2 — Render 1-page PDFs
      const { cvPdfPath, letterPdfPath } = await renderPdfs(profile, aiData, job, browser);
      console.log(`   📄 CV: ${path.basename(cvPdfPath)}`);
      console.log(`   ✉️  Letter: ${path.basename(letterPdfPath)}`);

      // Step 3 — Push to Telegram
      await sendTelegramAlert(job, aiData, cvPdfPath, letterPdfPath);
      console.log(`   📱 Sent to Telegram!\n`);

      // Step 4 — Save to Firebase
      await saveToFirebase(job, aiData);

      successCount++;

    } catch (err) {
      console.error(`   ❌ Failed on "${job.job_title}" @ ${job.company_name}: ${err.message}\n`);
      // Still mark as processed so we don't retry broken jobs on next run
      processed[job.id] = {
        title: job.job_title,
        company: job.company_name,
        fit_score: -1,
        error: err.message,
        processed_at: new Date().toISOString()
      };
      saveProcessedJobs(processed);
    }

    // Polite delay between jobs to avoid Gemini rate limits
    await new Promise(r => setTimeout(r, 4000));
  }

  await browser.close();
  console.log(`\n🎉 Done! Processed ${successCount} matching job offer(s).`);
}

// ─── Direct execution ─────────────────────────────────────────────────────────
if (process.argv[1] && process.argv[1].endsWith('multi_job_scraper.js')) {
  const maxJobs = parseInt(process.argv[2] || '3', 10);
  const minScore = parseInt(process.argv[3] || '60', 10);
  scrapeAndProcessJobs({ maxJobs, minScore });
}
