const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

/**
 * Scrapes recent public job postings from LinkedIn guest endpoint without login
 * @param {string} keywords - e.g. "Data Engineer", "Software Engineer"
 * @param {string} location - e.g. "Morocco", "Casablanca", "Paris", "Remote"
 * @param {number} limit - maximum number of jobs to fetch
 */
export async function scrapeLinkedInJobs(keywords = 'Data Engineer', location = 'Morocco', limit = 5) {
  console.log(`🔍 [LinkedIn] Searching for "${keywords}" in "${location}" (max: ${limit})...`);
  const encodedKeywords = encodeURIComponent(keywords);
  const encodedLocation = encodeURIComponent(location);
  const searchUrl = `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=${encodedKeywords}&location=${encodedLocation}&start=0`;

  try {
    const res = await fetch(searchUrl, {
      headers: { 'User-Agent': USER_AGENT }
    });

    if (!res.ok) {
      throw new Error(`LinkedIn search returned HTTP ${res.status}`);
    }

    const html = await res.text();
    const jobs = [];

    // Parse list of jobs using regex / Cheerio-like extraction
    const cardRegex = /<li[\s\S]*?<\/li>/g;
    const cards = html.match(cardRegex) || [];

    for (const card of cards) {
      if (jobs.length >= limit) break;

      // Extract Job ID
      const idMatch = card.match(/jobPosting:([0-9]+)/) || card.match(/data-entity-urn=\"[^\"]*jobPosting:([0-9]+)\"/);
      if (!idMatch) continue;
      const jobId = idMatch[1];

      // Extract Title
      const titleMatch = card.match(/<h3 class=\"base-search-card__title\">([\s\S]*?)<\/h3>/);
      const title = titleMatch ? titleMatch[1].replace(/<[^>]+>/g, '').trim() : 'Software Role';

      // Extract Company
      const companyMatch = card.match(/<h4 class=\"base-search-card__subtitle\">([\s\S]*?)<\/h4>/);
      const company = companyMatch ? companyMatch[1].replace(/<[^>]+>/g, '').trim() : 'Company';

      // Extract Location
      const locMatch = card.match(/<span class=\"job-search-card__location\">([\s\S]*?)<\/span>/);
      const jobLocation = locMatch ? locMatch[1].replace(/<[^>]+>/g, '').trim() : location;

      // Extract URL
      const linkMatch = card.match(/<a class=\"base-card__full-link[^\"]*\" href=\"([^\"]+)\"/);
      const jobUrl = linkMatch ? linkMatch[1].split('?')[0] : `https://www.linkedin.com/jobs/view/${jobId}`;

      jobs.push({
        id: `linkedin_${jobId}`,
        source: 'LinkedIn',
        job_id: jobId,
        job_title: title,
        company_name: company,
        company_location: jobLocation,
        job_url: jobUrl
      });
    }

    console.log(`📋 Found ${jobs.length} job cards. Fetching descriptions...`);

    // Fetch full descriptions for each job
    const detailedJobs = [];
    for (const job of jobs) {
      try {
        const descUrl = `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/${job.job_id}`;
        const descRes = await fetch(descUrl, {
          headers: { 'User-Agent': USER_AGENT }
        });

        if (descRes.ok) {
          const descHtml = await descRes.text();
          const markupMatch = descHtml.match(/<div class=\"show-more-less-html__markup[^\"]*\">([\s\S]*?)<\/div>/);
          if (markupMatch) {
            const cleanDesc = markupMatch[1]
              .replace(/<br\s*[\/]?>/gi, '\n')
              .replace(/<\/p>/gi, '\n\n')
              .replace(/<li>/gi, '• ')
              .replace(/<[^>]+>/g, '')
              .replace(/&nbsp;/g, ' ')
              .replace(/&amp;/g, '&')
              .replace(/&quot;/g, '"')
              .trim();

            job.job_description = cleanDesc;
            detailedJobs.push(job);
            console.log(`   ✓ ${job.job_title} @ ${job.company_name}`);
          }
        }
      } catch (e) {
        console.warn(`   ⚠️ Could not fetch description for ${job.job_title}:`, e.message);
      }

      // Small respectful delay between details requests
      await new Promise(r => setTimeout(r, 600));
    }

    return detailedJobs;
  } catch (error) {
    console.error('❌ LinkedIn scraper error:', error.message);
    return [];
  }
}
