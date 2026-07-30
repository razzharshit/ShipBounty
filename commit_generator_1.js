import jsonfile from "jsonfile";
import moment from "moment";
import simpleGit from "simple-git";

const path = "./data1.json";

const MESSAGES = [
  "refactor: optimize database query execution plans",
  "fix: handle null pointer exceptions in user auth middleware",
  "feat: add OAuth provider callback validation check",
  "docs: update API endpoint definitions in backend docs",
  "test: write comprehensive unit tests for webhook ingestion",
  "chore: bump dependencies and regenerate lock file",
  "style: enforce lint rules and clean import layouts",
  "fix: resolve CORS headers on local dev server",
  "feat: implement custom encryption utility for tokens",
  "refactor: extract environment config parsing logic"
];

const makeCommits = (n) => {
  if (n === 0) return simpleGit().push();
  
  const randomHour = Math.floor(Math.random() * 24);
  const randomMin = Math.floor(Math.random() * 60);

  // Range: April 1, 2026 to July 30, 2026
  const startDate = moment("2026-04-01");
  const endDate = moment("2026-07-30");
  const daysDiff = endDate.diff(startDate, "days");
  
  const randomDays = Math.floor(Math.random() * (daysDiff + 1));
  const date = startDate.clone()
    .add(randomDays, "days")
    .hour(randomHour)
    .minute(randomMin)
    .format();

  const data = { date };
  const message = MESSAGES[Math.floor(Math.random() * MESSAGES.length)];

  console.log(`[Script 1] Committing: "${message}" on ${date}`);

  jsonfile.writeFile(path, data, () => {
    simpleGit()
      .add([path])
      .commit(message, { "--date": date }, () => makeCommits(n - 1));
  });
};

// Target: 40 random commits
makeCommits(40);
