import jsonfile from "jsonfile";
import moment from "moment";
import simpleGit from "simple-git";

const path = "./data3.json";

const MESSAGES = [
  "ci: add automatic lint checks to pull requests workflow",
  "chore: setup docker-compose postgres container configurations",
  "feat: implement base transaction logs in database migrations",
  "test: write unit tests for worker queues and dispatcher handlers",
  "refactor: clean up deprecated environmental configurations",
  "fix: fix environment validation runtime exceptions on launch",
  "docs: document alembic migration instructions in setup runbook",
  "feat: connect connection pooling configurations to postgres",
  "chore: build base pipeline workflow action in github directory",
  "test: add mock tests for external stripe webhook integrations"
];

const makeCommits = (n) => {
  if (n === 0) return simpleGit().push();
  
  const randomHour = Math.floor(Math.random() * 24);
  const randomMin = Math.floor(Math.random() * 60);

  // Range: August 1, 2025 to December 31, 2025
  const startDate = moment("2025-08-01");
  const endDate = moment("2025-12-31");
  const daysDiff = endDate.diff(startDate, "days");
  
  let date;
  while (true) {
    const randomDays = Math.floor(Math.random() * (daysDiff + 1));
    const potentialDate = startDate.clone().add(randomDays, "days");
    // Ensure the date is NOT in October (Month index 9 is October)
    if (potentialDate.month() !== 9) {
      date = potentialDate
        .hour(randomHour)
        .minute(randomMin)
        .format();
      break;
    }
  }

  const data = { date };
  const message = MESSAGES[Math.floor(Math.random() * MESSAGES.length)];

  console.log(`[Script 3] Committing: "${message}" on ${date} (October is skipped)`);

  jsonfile.writeFile(path, data, () => {
    simpleGit()
      .add([path])
      .commit(message, { "--date": date }, () => makeCommits(n - 1));
  });
};

// Target: 42 random commits
makeCommits(42);
