import jsonfile from "jsonfile";
import moment from "moment";
import simpleGit from "simple-git";

const path = "./data4.json";

const MESSAGES = [
  "refactor: decouple API routes into nested modular routes",
  "fix: fix critical race condition in outbox dispatch queue",
  "feat: introduce customizable rate limiting restrictions",
  "docs: format changelog history for production release",
  "style: cleanup redundant loggers and obsolete comments",
  "fix: correct token payload claim signature validation logic",
  "feat: implement asynchronous cache layer using Redis client",
  "refactor: extract celery beat tasks into distinct module",
  "chore: setup standard project config validation schemas",
  "fix: handle timeout exceptions in external http calls"
];

const makeCommits = (n) => {
  if (n === 0) return simpleGit().push();
  
  const randomHour = Math.floor(Math.random() * 24);
  const randomMin = Math.floor(Math.random() * 60);

  // Range: May 1, 2025 to August 31, 2025
  const startDate = moment("2025-05-01");
  const endDate = moment("2025-08-31");
  const daysDiff = endDate.diff(startDate, "days");
  
  const randomDays = Math.floor(Math.random() * (daysDiff + 1));
  const date = startDate.clone()
    .add(randomDays, "days")
    .hour(randomHour)
    .minute(randomMin)
    .format();

  const data = { date };
  const message = MESSAGES[Math.floor(Math.random() * MESSAGES.length)];

  console.log(`[Script 4] Committing: "${message}" on ${date}`);

  jsonfile.writeFile(path, data, () => {
    simpleGit()
      .add([path])
      .commit(message, { "--date": date }, () => makeCommits(n - 1));
  });
};

// Target: 45 random commits
makeCommits(45);
