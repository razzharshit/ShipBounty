import jsonfile from "jsonfile";
import moment from "moment";
import simpleGit from "simple-git";

const path = "./data2.json";

const MESSAGES = [
  "feat: design responsive sidebar grid layout",
  "fix: repair modal focus trapping bug on closing",
  "refactor: migrate legacy components to functional TSX",
  "style: integrate custom SVG icons to replace lucide defaults",
  "perf: memoize expensive calculations in dashboard charts",
  "docs: add setup guidelines for frontend styling",
  "test: write Playwright end-to-end integration flows",
  "fix: fix navigation link highlighting on active path change",
  "feat: implement dark mode state preservation with localStorage",
  "style: upgrade tailwind styling configurations"
];

const makeCommits = (n) => {
  if (n === 0) return simpleGit().push();
  
  const randomHour = Math.floor(Math.random() * 24);
  const randomMin = Math.floor(Math.random() * 60);

  // Range: January 1, 2026 to April 30, 2026
  const startDate = moment("2026-01-01");
  const endDate = moment("2026-04-30");
  const daysDiff = endDate.diff(startDate, "days");

  const randomDays = Math.floor(Math.random() * (daysDiff + 1));
  const date = startDate.clone()
    .add(randomDays, "days")
    .hour(randomHour)
    .minute(randomMin)
    .format();

  const data = { date };
  const message = MESSAGES[Math.floor(Math.random() * MESSAGES.length)];

  console.log(`[Script 2] Committing: "${message}" on ${date}`);

  jsonfile.writeFile(path, data, () => {
    simpleGit()
      .add([path])
      .commit(message, { "--date": date }, () => makeCommits(n - 1));
  });
};

// Target: 38 random commits
makeCommits(38);
