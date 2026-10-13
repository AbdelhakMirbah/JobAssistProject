import fs from 'fs';
import path from 'path';

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Escape HTML special chars to prevent injection in templates */
function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Get the French half of a bilingual "FR / EN" string, or the whole string */
function firstHalf(str) {
  if (!str) return '';
  return str.split(/\s*\/\s*/)[0].trim();
}

// ─── CV Renderer ─────────────────────────────────────────────────────────────

/**
 * Hydrates cv_template.html with master profile + AI-tailored data.
 *
 * @param {Object} profile      - master_profile.json
 * @param {Object} tailoredData - fields returned by Gemini AI
 *   tailored_summary   {string}
 *   target_headline    {string}
 *   experience         {Array}  - AI-selected experience entries
 *   projects           {Array}  - AI-selected project entries
 */
export function renderCvHtml(profile, tailoredData = {}) {
  const p = profile.personal || {};

  // ── Summary ─────────────────────────────────────────────────────────────────
  let summary = tailoredData.tailored_summary || '';
  if (!summary) {
    summary = typeof profile.summary === 'object'
      ? (profile.summary.fr || profile.summary.en || '')
      : (profile.summary || '');
  }

  const headline = tailoredData.target_headline || p.headline || 'Ingénieur Logiciel Junior | Data Engineer';

  // ── Skills ───────────────────────────────────────────────────────────────────
  const skillsObj = profile.skills || {};
  const categoryLabels = {
    data_engineering:       'Data Engineering',
    languages:              'Langages',
    cloud_and_devops:       'Cloud & DevOps',
    frameworks_and_backend: 'Développement Web & Backend',
    databases:              'Bases de données',
    ai_and_analytics:       'Analytics & IA',
    tools_and_methods:      'Outils & Méthodes'
  };

  const skillsHtml = Object.entries(skillsObj)
    .filter(([, items]) => Array.isArray(items) && items.length > 0)
    .map(([key, items]) => {
      const label = categoryLabels[key] || key.replace(/_/g, ' ');
      return `
        <div class="skill-row">
          <span class="skill-label">${esc(label)} :</span>
          <span class="skill-values">${esc(items.join(', '))}</span>
        </div>`;
    })
    .join('\n');

  // ── Experience ───────────────────────────────────────────────────────────────
  // Priority: AI-tailored list → fallback to top 3 from profile
  const expSource = (tailoredData.experience && tailoredData.experience.length > 0)
    ? tailoredData.experience.slice(0, 3)
    : (profile.experience || []).slice(0, 3);

  const expHtml = expSource.map(exp => {
    // Merge AI entry with profile data if the AI entry is thin
    const profileMatch = (profile.experience || []).find(pe =>
      pe.company && exp.company &&
      pe.company.toLowerCase().includes(exp.company.toLowerCase().split(' ')[0])
    ) || {};

    const title     = exp.title     || profileMatch.title     || '';
    const company   = exp.company   || profileMatch.company   || '';
    const location  = exp.location  || profileMatch.location  || '';
    const startDate = exp.start_date || profileMatch.start_date || '';
    const endDate   = exp.end_date   || profileMatch.end_date   || '';
    const bullets   = (exp.bullets  || profileMatch.bullets   || []).slice(0, 3);

    const bulletsHtml = bullets.map(b => `<li>${esc(b)}</li>`).join('\n');
    const dateStr = startDate ? `${esc(startDate)} – ${esc(endDate)}` : '';
    const locStr  = location  ? ` | ${esc(firstHalf(location))}` : '';

    return `
      <div class="entry">
        <div class="entry-header">
          <div>
            <span class="entry-title">${esc(title)}</span> –
            <span class="entry-company">${esc(company)}</span>
            <span class="entry-location">${locStr}</span>
          </div>
          <span class="entry-date">${dateStr}</span>
        </div>
        <ul class="entry-bullets">
          ${bulletsHtml}
        </ul>
      </div>`;
  }).join('\n');

  // ── Projects ─────────────────────────────────────────────────────────────────
  // Priority: AI-tailored list → fallback to top 2 from profile
  const projSource = (tailoredData.projects && tailoredData.projects.length > 0)
    ? tailoredData.projects.slice(0, 2)
    : (profile.projects || []).slice(0, 2);

  const projHtml = projSource.map(proj => {
    // Merge with profile project data if AI entry is thin
    const profileProj = (profile.projects || []).find(pp =>
      pp.name && proj.name && pp.name.toLowerCase().includes(proj.name.toLowerCase().split(' ')[0])
    ) || {};

    const name      = proj.name        || profileProj.name      || '';
    const techStack = proj.tech_stack   || profileProj.tech_stack || [];
    const date      = proj.date         || profileProj.date       || '';
    const desc      = proj.description  || profileProj.description_en || profileProj.description || '';

    const techStr = Array.isArray(techStack) && techStack.length
      ? ` (${esc(techStack.join(', '))})`
      : '';

    return `
      <div class="entry">
        <div class="entry-header">
          <div>
            <span class="entry-title">${esc(name)}</span>
            <span class="entry-location">${techStr}</span>
          </div>
          <span class="entry-date">${esc(firstHalf(date))}</span>
        </div>
        <ul class="entry-bullets">
          <li>${esc(desc)}</li>
        </ul>
      </div>`;
  }).join('\n');

  // ── Education ────────────────────────────────────────────────────────────────
  const eduHtml = (profile.education || []).slice(0, 2).map(edu => {
    const degree = esc(firstHalf(edu.degree));
    return `
      <div class="entry">
        <div class="entry-header">
          <div>
            <span class="entry-title">${degree}</span> –
            <span class="entry-company">${esc(edu.institution)}</span>
          </div>
          <span class="entry-date">${esc(edu.start_date)} – ${esc(edu.end_date)}</span>
        </div>
      </div>`;
  }).join('\n');

  // ── Certifications (inline, top 5) ───────────────────────────────────────────
  const certsInline = (profile.certifications || [])
    .slice(0, 5)
    .map(c => typeof c === 'string' ? c : `${c.name} (${c.issuer})`)
    .join(', ');

  // ── Languages ────────────────────────────────────────────────────────────────
  const langsInline = (profile.personal?.languages || [])
    .map(l => `${l.name} (${firstHalf(l.level)})`)
    .join(', ');

  // ── Hydrate template ─────────────────────────────────────────────────────────
  const templatePath = path.resolve(process.cwd(), 'templates/cv_template.html');
  let html = fs.readFileSync(templatePath, 'utf8');

  return html
    .replace(/{{FULL_NAME}}/g,            esc(p.full_name))
    .replace(/{{TARGET_HEADLINE}}/g,      esc(headline))
    .replace(/{{EMAIL}}/g,                esc(p.email))
    .replace(/{{PHONE}}/g,                esc(p.phone))
    .replace(/{{LOCATION}}/g,             esc(p.location))
    .replace(/{{LINKEDIN_DISPLAY}}/g,     esc((p.linkedin  || '').replace('https://', '')))
    .replace(/{{PORTFOLIO_DISPLAY}}/g,    esc((p.portfolio || '').replace('https://', '')))
    .replace(/{{TAILORED_SUMMARY}}/g,     esc(summary))
    .replace(/{{SKILLS_ROWS}}/g,          skillsHtml)
    .replace(/{{EXPERIENCE_ENTRIES}}/g,   expHtml)
    .replace(/{{PROJECTS_ENTRIES}}/g,     projHtml)
    .replace(/{{EDUCATION_ENTRIES}}/g,    eduHtml)
    .replace(/{{CERTIFICATIONS_INLINE}}/g, esc(certsInline))
    .replace(/{{LANGUAGES_INLINE}}/g,     esc(langsInline));
}

// ─── Cover Letter Renderer ────────────────────────────────────────────────────

/**
 * Hydrates cover_letter_template.html with profile + AI cover letter content.
 *
 * @param {Object} profile      - master_profile.json
 * @param {Object} tailoredData - fields returned by Gemini AI + job metadata
 */
export function renderCoverLetterHtml(profile, tailoredData = {}) {
  const p = profile.personal || {};
  const company  = tailoredData.company_name      || 'L\'Entreprise';
  const jobTitle = tailoredData.job_title          || 'Poste Visé';
  const location = tailoredData.company_location   || '';
  const headline = tailoredData.target_headline    || p.headline || '';

  const today = new Date().toLocaleDateString('fr-FR', {
    day: 'numeric', month: 'long', year: 'numeric'
  });

  // Default cover letter paragraphs (used only if AI did not produce them)
  const paragraphs = tailoredData.cover_letter_paragraphs || [
    `Diplômé Ingénieur d'État en Informatique et Réseaux (Génie Logiciel) de l'EMSI, passionné par le développement logiciel et le Data Engineering, je vous soumets ma candidature pour le poste de ${jobTitle} au sein de ${company}.`,
    `Au cours de mes expériences, notamment chez LEONI WS et Daman Cash (Groupe BMCE), j'ai développé des flux ETL avec Pentaho, alimenté des Data Warehouses et automatisé la consolidation financière. J'ai également conçu des pipelines temps réel avec Apache Kafka et Spring Boot, et déployé des applications web full-stack.`,
    `Intégrer ${company} représente pour moi l'opportunité de mettre ma rigueur technique et ma motivation au service de vos projets. Je reste disponible pour un entretien à votre convenance.`
  ];

  const paragraphsHtml = paragraphs
    .map(para => `<p>${esc(para)}</p>`)
    .join('\n');

  const templatePath = path.resolve(process.cwd(), 'templates/cover_letter_template.html');
  let html = fs.readFileSync(templatePath, 'utf8');

  return html
    .replace(/{{FULL_NAME}}/g,                esc(p.full_name))
    .replace(/{{TARGET_HEADLINE}}/g,          esc(headline))
    .replace(/{{EMAIL}}/g,                    esc(p.email))
    .replace(/{{PHONE}}/g,                    esc(p.phone))
    .replace(/{{LOCATION}}/g,                 esc(p.location))
    .replace(/{{LINKEDIN_DISPLAY}}/g,         esc((p.linkedin || '').replace('https://', '')))
    .replace(/{{COMPANY_NAME}}/g,             esc(company))
    .replace(/{{COMPANY_LOCATION}}/g,         esc(location))
    .replace(/{{JOB_TITLE}}/g,                esc(jobTitle))
    .replace(/{{TODAY_DATE}}/g,               `Le ${today}`)
    .replace(/{{SALUTATION}}/g,               esc(tailoredData.salutation || 'Madame, Monsieur,'))
    .replace(/{{COVER_LETTER_PARAGRAPHS}}/g,  paragraphsHtml)
    .replace(/{{COMPLIMENTARY_CLOSE}}/g,      esc(tailoredData.complimentary_close || 'Je vous prie d\'agréer, Madame, Monsieur, l\'expression de mes salutations distinguées.'));
}
