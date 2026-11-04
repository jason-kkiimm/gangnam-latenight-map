// PreToolUse hook: Claude Code가 .env 파일을 읽거나 고치거나 명령어로 다루는 것을 막는다.
// .env.example 은 허용한다. 표준입력으로 도구 호출 JSON을 받는다. (Node.js, Windows 지원)
const path = require("path");

const MSG =
  "차단됨: .env에는 API 키가 들어 있어서 Claude Code가 읽거나 고칠 수 없습니다. " +
  "키 이름만 필요하면 .env.example을 보세요. .env를 바꿔야 하면 직접 편집해 주세요.";

// 파일 경로가 .env 계열인가 (.env, .env.local ...). .env.example 은 아니다.
function isEnvPath(p) {
  if (typeof p !== "string" || !p) return false;
  const base = path.win32.basename(p.replace(/\//g, "\\")).toLowerCase();
  if (base === ".env.example") return false;
  return base === ".env" || base.startsWith(".env.");
}

// 명령어(Bash/PowerShell) 안에 .env가 들어 있는가. 예: cat .env, type .\.env, source ./.env
// ".venv", "dotenv", ".env.example", ".environment" 는 걸리지 않는다.
const ENV_IN_CMD = /(?<![\w.-])\.env(?!\.example(?![\w-]))(?![A-Za-z0-9_-])/i;

function shouldBlock(input) {
  const ti = (input && input.tool_input) || {};
  for (const key of ["file_path", "path", "notebook_path"]) {
    if (isEnvPath(ti[key])) return true;
  }
  // Glob/Grep 의 패턴, Bash/PowerShell 의 명령어
  for (const key of ["pattern", "glob", "command"]) {
    if (typeof ti[key] === "string" && ENV_IN_CMD.test(ti[key])) return true;
  }
  return false;
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let input = {};
  try {
    input = JSON.parse(raw);
  } catch (e) {
    // 입력을 못 읽으면 막는 쪽이 안전하다.
    input = { tool_input: { command: ".env" } };
  }
  if (shouldBlock(input)) {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: MSG,
        },
      })
    );
  }
  process.exit(0);
});
