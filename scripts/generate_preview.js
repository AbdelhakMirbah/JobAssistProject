import fs from 'fs';
import path from 'path';
import { renderCvHtml, renderCoverLetterHtml } from './render_html.js';

async function generatePreview() {
  const profilePath = path.resolve(process.cwd(), 'data/master_profile.json');
  if (!fs.existsSync(profilePath)) {
    console.error('❌ data/master_profile.json not found.');
    return;
  }

  const profile = JSON.parse(fs.readFileSync(profilePath, 'utf8'));

  // Ensure output dir exists
  const outputDir = path.resolve(process.cwd(), 'output');
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  console.log('🔄 Rendering sample CV and Cover Letter HTML...');
  const cvHtml = renderCvHtml(profile);
  const letterHtml = renderCoverLetterHtml(profile, {
    company_name: 'Acme Corp',
    job_title: 'Senior Automation & Full-Stack Engineer',
    company_location: 'Paris, France'
  });

  const cvHtmlPath = path.join(outputDir, 'preview_cv.html');
  const letterHtmlPath = path.join(outputDir, 'preview_cover_letter.html');

  fs.writeFileSync(cvHtmlPath, cvHtml, 'utf8');
  fs.writeFileSync(letterHtmlPath, letterHtml, 'utf8');

  console.log(`✅ Generated HTML previews:`);
  console.log(`   📄 CV: ${cvHtmlPath}`);
  console.log(`   ✉️ Cover Letter: ${letterHtmlPath}`);

  // Check if Puppeteer is installed to also generate PDF directly
  try {
    const puppeteer = await import('puppeteer');
    console.log('🔄 Puppeteer detected, generating PDF files...');

    const browser = await puppeteer.default.launch({
      headless: 'new',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    // 1. CV PDF
    const pageCv = await browser.newPage();
    await pageCv.setContent(cvHtml, { waitUntil: 'networkidle0' });
    const cvPdfPath = path.join(outputDir, 'preview_cv.pdf');
    await pageCv.pdf({
      path: cvPdfPath,
      format: 'A4',
      printBackground: true,
      margin: { top: '0mm', right: '0mm', bottom: '0mm', left: '0mm' }
    });
    console.log(`   🎉 CV PDF created: ${cvPdfPath}`);

    // 2. Letter PDF
    const pageLetter = await browser.newPage();
    await pageLetter.setContent(letterHtml, { waitUntil: 'networkidle0' });
    const letterPdfPath = path.join(outputDir, 'preview_cover_letter.pdf');
    await pageLetter.pdf({
      path: letterPdfPath,
      format: 'A4',
      printBackground: true,
      margin: { top: '0mm', right: '0mm', bottom: '0mm', left: '0mm' }
    });
    console.log(`   🎉 Cover Letter PDF created: ${letterPdfPath}`);

    await browser.close();
  } catch (err) {
    console.log('\n💡 Note: To generate PDF via Node directly, run `npm install` once.');
    console.log('Or use Docker Compose where Gotenberg renders PDFs automatically.');
  }
}

generatePreview();
