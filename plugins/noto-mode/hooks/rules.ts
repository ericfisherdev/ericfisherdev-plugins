// The pattern lists: what is never approved on its own (HARD, mirroring the
// block list of Claude Code's auto mode), what always goes to the classifier
// (SOFT), and the command sets the rules read. Pure data.

export type Rule = readonly [RegExp, string]

/** Never auto-approved: the person decides. Matched against the whole command with quoted text blanked. */
export const HARD: readonly Rule[] = [
  [/(^|[\s;&|(])(sudo|doas|pkexec|runas)(\s|$)/i, 'privilege escalation'],
  [/(^|[\s;&|(])su(\s+-|\s+root|\s*$)/i, 'privilege escalation'],
  [/\bgit\s+push\b[^|;&]*(\s--force\b|\s-f\b|\s--force-with-lease|\s\+[^\s:]*:|--mirror|\s--delete\b|\s-d\b|\s:\S+)/i, 'a force push or a remote branch deletion'],
  [/\bgit\s+(reset\s+--(hard|merge)|checkout\s+(-f|--force)\b|checkout\s+--\s|checkout\s+\.(\s|$)|restore\b(?![^|;&]*--staged)|restore\b[^|;&]*(--worktree|\s-W\b)|clean\s+-\w*[fdx]|clean\s+--force|stash\s+(drop|clear)|commit\b[^|;&]*--amend|remote\s+(set-url|add|remove|rm|rename|prune)|filter-branch|filter-repo|branch\s+(-\w*[DM]\b|--delete\s+--force)|update-ref\s+-d|reflog\s+(expire|delete)|gc\b[^|;&]*--prune|switch\s+(-f|--discard-changes|--force)|prune\b|worktree\s+(remove\s+(-f|--force)|prune)|rebase\b[^|;&]*(\s-i\b|--interactive)|rm\s+-\w*r\w*f|rm\s+(-\w+\s+)*\.(\s|$))/i, 'a git command that discards history or uncommitted work'],
  [/\bgit\b[^|;&]*(--no-verify|-c\s+core\.hookspath|core\.hookspath=|-c\s+credential\.|http\.sslverify=false)/i, 'disarms git safety hooks or changes credential handling'],
  [/\b(terraform|terragrunt|tofu)\s+(destroy|apply)\b|\b(pulumi|cdk|cdktf|sst)\s+(destroy|deploy|up|remove)\b/i, 'an infrastructure apply or destroy'],
  [/--dangerously-skip-permissions|--no-sandbox|--insecure\b|--no-check-certificate|--trust-all-certs|-SkipCertificateCheck|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['"]?0|GIT_SSL_NO_VERIFY\s*=|PYTHONHTTPSVERIFY\s*=\s*['"]?0|--allow-unauthenticated|--force-yes|--disable-host-check|strict-ssl\s*(=|\s)\s*false|\bcurl\b[^|;&]*(\s-k\b|\s-[a-zA-Z]*k[a-zA-Z]*(\s|$))/i, 'a flag that disarms a safety guard'],
  [/\b(mkfs(\.\w+)?|fdisk|sfdisk|parted|wipefs|diskpart|shred|srm)\b|\bdd\s+if=|\bformat(\.com)?\s+[a-z]:/i, 'destroys a disk or wipes data'],
  [/\b(shutdown|reboot|halt|poweroff|restart-computer|stop-computer|logoff|init\s+[06]|systemctl\s+(poweroff|reboot|halt|suspend|hibernate))\b/i, 'shuts the machine down'],
  [/:\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:|\bkill\s+(-\w+\s+)?-1\b|\bkillall5\b/i, 'kills every process'],
  [/\bgh\s+(pr\s+merge|pr\s+review\b[^|;&]*(--approve|\s-a\b)|repo\s+(delete|archive|edit\b[^|;&]*--visibility)|api\b[^|;&]*(-X|--method)[\s=]*(DELETE|PUT|PATCH)\b|secret\s+(set|delete|remove)|variable\s+set|auth\s+(token|login|refresh|setup-git)|gist\s+create|release\s+delete|ssh-key\s+add|gpg-key\s+add|workflow\s+(disable|enable)|run\s+(cancel|delete)|repo\s+deploy-key|api\b[^|;&]*collaborators)/i, 'merges, approves, grants access or prints a token via gh'],
  [/\b(aws\s+(s3\s+(rm|rb)\b[^|;&]*(--recursive|--force)|s3\s+rb\b|s3api\s+delete-(bucket|objects)|iam\b|sts\s+assume-role|ec2\s+(terminate-instances|delete-)|rds\s+(delete|modify)|cloudformation\s+(delete-stack|deploy|update-stack)|route53|acm\b|secretsmanager\s+(put|create|update|delete|restore)|ssm\s+put-parameter|lambda\s+(update|delete|create)|eks\s+(delete|update)|ecs\s+(update-service|delete)|dynamodb\s+delete-table|organizations|kms\s+(disable|schedule-key-deletion|put-key-policy))|gsutil\s+(rm|rb)\b[^|;&]*-r|gsutil\s+iam|gcloud\s+(iam|projects\s+(delete|add-iam|set-iam|remove-iam)|compute\s+instances\s+delete|sql\s+instances\s+(delete|patch)|secrets\s+(create|versions\s+(add|destroy)|delete)|dns|run\s+deploy|functions\s+deploy|app\s+deploy|container\s+clusters\s+delete)|az\s+(role|ad\s+(app|sp|user|group)|storage\s+(container|blob|account)\s+delete|group\s+delete|keyvault\s+(secret|key|certificate)\s+(set|delete|import)|network\s+dns|webapp\s+(deploy|deployment)|vm\s+delete|aks\s+delete))\b/i, 'changes cloud infrastructure, IAM or secrets'],
  [/\b(kubectl|oc)\s+(delete|apply|create|replace|patch|edit|drain|cordon|uncordon|exec|port-forward|scale|rollout\s+(restart|undo)|taint|label|annotate|set\s+image)\b|\bhelm\s+(install|upgrade|uninstall|delete|rollback)\b|\bdocker\s+(system\s+prune|volume\s+(rm|prune)|image\s+prune|container\s+prune|rmi?\s+-\w*f|push|login|logout)\b|\b(docker[\s-]compose|podman[\s-]compose)\s+down\b[^|;&]*(-v|--volumes)|\bflux\s+(reconcile|delete|suspend)|\bargocd\s+app\s+(sync|delete)/i, 'changes shared infrastructure'],
  [/\b(vercel\b[^|;&]*--prod|vercel\s+(deploy|promote|rollback|alias)|netlify\s+deploy\b[^|;&]*--prod|firebase\s+deploy|fly(ctl)?\s+(deploy|scale|machines?\s+(destroy|kill))|heroku\s+(releases:rollback|config:(set|unset)|pg:reset|apps:destroy|container:release)|serverless\s+(deploy|remove)|sls\s+(deploy|remove)|wrangler\s+(publish|deploy|delete)|amplify\s+(push|publish)|eb\s+(deploy|terminate)|cap\s+\w+\s+deploy|ansible-playbook|npm\s+(publish|unpublish|deprecate|owner|access|dist-tag|token|login|adduser|logout)|yarn\s+(publish|npm\s+(publish|login|logout))|pnpm\s+(publish|login|logout)|cargo\s+(publish|login|yank|owner)|twine\s+upload|flit\s+publish|poetry\s+publish|gem\s+(push|yank|signin)|nuget\s+(push|delete)|dotnet\s+nuget\s+(push|delete)|mvn\b[^|;&]*\bdeploy\b|gradle\w*\b[^|;&]*\bpublish|goreleaser\s+release|railway\s+(up|deploy)|render\s+deploy|sam\s+deploy|copilot\s+(deploy|svc\s+deploy)|kamal\s+deploy|docker\s+buildx\s+build\b[^|;&]*--push)\b/i, 'a production deploy or a package publish'],
  [/\b((npx\s+)?prisma\s+migrate\s+(deploy|reset)|prisma\s+db\s+push\b[^|;&]*--force-reset|rails\s+db:(drop|reset|schema:load|purge)|rake\s+db:(drop|reset|purge)|(drizzle-kit|dbmate|flyway|liquibase|alembic|knex|sequelize(-cli)?|typeorm|goose|atlas|sqlx)\s+\S*(drop|reset|rollback|downgrade|clean|down)\b)/i, 'drops or resets a database'],
  [/\b(vault\s+(kv\s+(put|delete|destroy|metadata\s+delete)|write|delete|token\s+create|policy\s+write|auth\s+enable)|op\s+(item\s+(create|edit|delete)|vault\s+(create|delete))|doppler\s+secrets\s+(set|delete|upload)|certbot|acme\.sh|openssl\s+(req|x509|ca)\b|mkcert|cfssl|step\s+ca)\b/i, 'writes a secret manager, DNS or TLS material'],
  [/\b(npm\s+config\s+set\s+(registry|proxy|https-proxy|strict-ssl)|npm\s+(i|install|add|ci)\b[^|;&]*--registry|yarn\s+config\s+set\s+(registry|npmRegistryServer|httpProxy|httpsProxy|enableStrictSsl)|pnpm\s+config\s+set\s+(registry|proxy|https-proxy|strict-ssl)|pip3?\s+install\b[^|;&]*(--index-url|\s-i\s|--extra-index-url|--trusted-host|--find-links|\s-f\s)|pip3?\s+config\s+set|uv\s+pip\s+install\b[^|;&]*(--index-url|--extra-index-url)|git\s+config\b[^|;&]*(url\.[^\s]*\.insteadof|http\.proxy|https\.proxy|credential\.helper|http\.sslverify|core\.sshcommand|core\.hookspath)|(export|set|setx|\$env:)\s*(https?_proxy|all_proxy|npm_config_registry|pip_index_url|pip_extra_index_url|anthropic_base_url|anthropic_api_url|openai_base_url|openai_api_base|docker_host|kubeconfig|aws_endpoint_url|goproxy|nuget_\w*source)\b|docker\s+(login|logout)|gem\s+sources\s+(-a|--add|-r|--remove)|conda\s+config\s+--(add|set)\s+channels)/i, 'repoints a registry, proxy, endpoint or credential helper'],
  [/\b(nc|ncat|netcat)\b[^|;&]*(\s-[a-z]*e\s|\s-c\s|\s-[a-z]*l\b)|\bsocat\b|\/dev\/(tcp|udp)\/|\b(ngrok|cloudflared\s+tunnel|localtunnel|lt\s+--port|bore\s+local|frpc|chisel\s+client|serveo|tailscale\s+(funnel|serve)|ssh\s+(-\S*\s+)*-R\b|ssh\s+-\w*R\w*\s|telebit|pagekite|localhost\.run|pinggy)\b/i, 'opens a tunnel, listener or reverse shell'],
  [/\bssh\s+(-\S+(\s+\S+)?\s+)*[^-\s]+\s*$/i, 'an interactive remote shell'],
  [/\b(kubectl\s+exec\b[^|;&]*(-it|-ti|-t\s+-i)|docker\s+exec\b[^|;&]*(-it|-ti)|docker\s+run\b[^|;&]*(-it|-ti))/i, 'an interactive shell into a container'],
  [/\b(crontab\s+(-e|-r|-i|\S+$)|systemctl\s+(enable|disable|start|stop|restart|mask|unmask|daemon-reload|edit)|launchctl\s+(load|unload|bootstrap|bootout|enable|disable)|schtasks\b|sc(\.exe)?\s+(create|delete|config|start|stop|failure)|reg(\.exe)?\s+(add|delete|import|restore|load)|(set|new|remove)-itemproperty\b[^|;&]*hk(lm|cu|cr|u|cc):|(new|remove|rename)-item\b[^|;&]*hk(lm|cu|cr|u|cc):|netsh\b|iptables|ip6tables|nft\b|ufw\b|pfctl|firewall-cmd|(new|set|remove)-netfirewallrule|set-executionpolicy|(set|add|remove)-mppreference|bcdedit|wmic\b|dism\b|sfc\s+\/scannow|gpupdate|secedit|net\s+(user|localgroup|share|use)\b|dscl\b|usermod|useradd|userdel|groupadd|passwd\b|chsh\b|visudo|\/etc\/(sudoers|passwd|shadow|hosts|fstab|crontab|cron\.|ssh\/sshd_config|systemd)|hostnamectl|timedatectl\s+set|defaults\s+write\s+(\/library|com\.apple)|nvram\b|csrutil|spctl\s+--master-disable|tccutil)/i, 'changes system services, firewall, registry, users or scheduled tasks'],
  [/\b(rm|del|erase|remove-item|ri|rd|rmdir)\b[^|;&]*(\/tmp\/|\/var\/tmp\/|\$tmpdir|\$env:temp|\$env:tmp|%temp%|%tmp%|\/dev\/shm\/|~\/\.cache\/|\$home\/\.cache\/|appdata[\\\/]local[\\\/]temp|\.cache[\\\/])[^|;&]*([*?]|-mtime|-atime|-ctime|-older|-min)|\bfind\s+(\/tmp|\/var\/tmp|\$tmpdir|\$env:temp|~\/\.cache)\b[^|;&]*(-delete|-exec\s+rm)|\bget-childitem\b[^|;&]*(temp|\.cache)[^|;&]*\|\s*remove-item/i, 'wildcard deletion in a shared scratch or cache directory'],
  [/169\.254\.169\.254|metadata\.google\.internal|100\.100\.100\.200|fd00:ec2::254|169\.254\.170\.2|metadata\.azure/i, 'queries cloud instance metadata credentials'],
  [/\b(nmap|masscan|arp-scan|zmap|netdiscover|fping\s+-g|nbtscan|rustscan)\b/i, 'scans the network'],
  [/\b(pastebin\.com|hastebin|ix\.io|sprunge\.us|termbin\.com|transfer\.sh|file\.io|0x0\.st|dpaste|paste\.rs|ghostbin|bpa\.st|paste\.ee|catbox\.moe|gofile\.io|anonfiles|bashupload|temp\.sh|croc\s+send|magic-wormhole|ffsend)\b/i, 'posts data to a public paste or file-sharing service'],
  [/\b(history\s+-[cw]|clear-history|unset\s+histfile|histfile\s*=|histsize\s*=\s*0|set\s+\+o\s+history|rm\b[^|;&]*(\.bash_history|\.zsh_history|consolehost_history))\b/i, 'tampers with shell history'],
  [/\bchmod\b[^|;&]*(\b[0-7]?77[0-7]\b|(^|\s|,)([ug]*[oa][ugoa]*\+[rwxst]*w|\+[rwxst]*w)|\s\/\s*$|\s\/(etc|usr|bin|sbin|lib|var|boot|sys|proc|root|home)\b)|\bchown\b[^|;&]*(\s\/\s*$|\s\/(etc|usr|bin|sbin|lib|var|boot|root)\b)|\bicacls\b[^|;&]*(everyone|authenticated users|\*s-1-1-0)[^|;&]*:\s*\(?f|\btakeown\b[^|;&]*(\/r|c:\\\s*$|\\windows)/i, 'opens permissions wide or changes ownership of system paths'],
  [/\b(aws\s+(secretsmanager\s+get-secret-value|ssm\s+get-parameters?\b[^|;&]*--with-decryption|configure\s+(export-credentials)|sts\s+get-session-token|iam\s+create-access-key)|gcloud\s+(auth\s+print-(access|identity)-token|secrets\s+versions\s+access|auth\s+application-default\s+print-access-token)|az\s+(account\s+get-access-token|keyvault\s+secret\s+show|ad\s+sp\s+credential)|vault\s+(kv\s+get|read|token\s+lookup|print\s+token)|op\s+(read|item\s+get|signin)|gh\s+auth\s+token|glab\s+auth\s+status\s+--show-token|kubectl\s+config\s+view\b[^|;&]*--raw|heroku\s+auth:token|vercel\s+env\s+pull|npm\s+token\s+list|security\s+find-(generic|internet)-password|cmdkey\s+\/list|get-storedcredential)\b/i, 'prints a live credential or token'],
  [/\brsync\b[^|;&]*--delete/i, 'a sync that deletes at the destination'],
  [/\b(powershell|pwsh)(\.exe)?\b[^|;&]*(-e|-ec|-enc|-encodedcommand)\s+[A-Za-z0-9+/=]{16,}/i, 'an encoded PowerShell command'],
]

/** Always judged by the classifier (or asked with it off), never allowed by rule. */
export const SOFT: readonly Rule[] = [
  [/\b(cat|type|get-content|gc|more|less|head|tail|bat|strings|xxd|hexdump|od)\b[^|;&]*(\.env(\.\w+)?\b|\.aws[\\\/]credentials|\.netrc|_netrc|\.git-credentials|\.npmrc|\.pypirc|\.docker[\\\/]config\.json|\.kube[\\\/]config|id_rsa\b|id_ed25519\b|\.pem\b|\.ssh[\\\/]|\.gnupg[\\\/]|\.config[\\\/]gh[\\\/]hosts|credentials\.json|service[-_]account\S*\.json|secrets?\.(json|ya?ml|toml))/i, 'reads a credentials file into the transcript'],
  [/(^|[\s;&|(])(printenv|env|set)\s*($|[;&|])|get-childitem\s+env:|\b(gci|ls|dir)\s+env:|\$env:\w*(key|secret|token|password|passwd|credential)\w*|\becho\b[^|;&]*\$\{?\w*(key|secret|token|password|passwd|credential)\w*/i, 'prints the environment or a secret-looking variable'],
  [/\bcurl\b[^|;&]*(\s-H\s|--header|\s-u\s|--user\b|--oauth2-bearer|--netrc)|\b(iwr|irm|invoke-webrequest|invoke-restmethod)\b[^|;&]*(-headers|-credential|-token|-authentication|-usedefaultcredentials)/i, 'sends a credential over HTTP'],
  [/\bkubectl\s+(get|describe)\s+secrets?\b|\bdocker\s+config\b|\bheroku\s+config(?!:unset)\b|\bnetlify\s+env:(get|list)|\bfly(ctl)?\s+secrets\s+list|\brailway\s+variables|\bsupabase\s+secrets\s+list|\bwrangler\s+secret\s+list|\bdoppler\s+secrets(\s+(get|download))?\s*$|\baws\s+configure\s+(get|list)/i, 'lists secrets or configuration that may hold credentials'],
]

/** Destructive SQL, checked against the raw text (quotes included) when a database client runs. */
export const SQL_DESTRUCTIVE = /\b(DROP\s+(DATABASE|SCHEMA|TABLE|COLLECTION)|TRUNCATE\s+(TABLE\s+)?\w|DELETE\s+FROM\s+\S+\s*(;|$|["'])|db\.dropDatabase|\.drop\(\)|FLUSHALL|FLUSHDB)/i

/** A pipeline whose tail is an interpreter: ask when the head downloads or decodes, else classify. */
export const PIPE_TO_INTERPRETER =
  /\|\s*(sudo\s+)?((ba|z|k|da|fi)?sh|iex|invoke-expression|python3?|node|deno|bun|perl|ruby|php|pwsh|powershell|cmd)(\s|$)/i
export const DOWNLOADER =
  /\b(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod|fetch|base64|certutil|xxd|openssl\s+enc|gpg|nc|ncat)\b/i

/** Spellings of Claude Code's own configuration and transcripts. */
export const CLAUDE_INTERNAL =
  /[~\\\/]\.claude[\\\/](projects|sessions|history|settings[^\\\/\s]*\.json|\.credentials|plugins|keybindings|statsig|todos|dev-mods|hooks)|(^|[\s"'\\\/])\.claude[\\\/]settings[^\\\/\s]*\.json|(^|[\s"'\\\/])\.claude-plugin[\\\/]/i

const set = (names: string): ReadonlySet<string> => new Set(names.split(/\s+/).filter(Boolean))

/** Commands that read and print and change nothing. */
export const READ_ONLY = set(`
  ls dir cat head tail less more wc grep egrep fgrep rg ag fd locate which where whereis type file stat du df pwd
  echo printf true false : date cal uname hostname whoami id uptime tree basename dirname realpath readlink sort uniq cut
  awk gawk mawk sed tr diff cmp comm md5sum sha1sum sha256sum shasum cksum xxd hexdump od strings jq yq column nl tac rev
  fold expand unexpand seq test [ [[ sleep ps top tasklist nproc free arch man help info apropos whatis getconf
  clear history exit return wait jobs bg fg hash ulimit umask tty stty tput
  nslookup dig host traceroute tracert ping ipconfig ifconfig ip netstat ss route arp
  bat exa eza lsd ncdu tldr cheat
  get-childitem gci get-content gc get-item gi get-location gl get-command gcm get-date get-process gps get-service gsv
  test-path resolve-path rvpa measure-object measure select-object select where-object where sort-object sort group-object
  group format-table ft format-list fl format-wide fw out-string out-host out-null out-default write-output write-host
  write-verbose write-warning write-information write-debug write-error get-help get-member gm get-host split-path
  join-path convertfrom-json convertto-json convertfrom-csv convertto-csv get-filehash compare-object compare get-variable gv
  get-module get-psdrive get-alias gal get-unique get-random get-culture get-uiculture get-computerinfo get-itemproperty gp
  get-itempropertyvalue get-acl get-childitem get-history get-job get-event get-eventlog get-winevent get-wmiobject get-ciminstance
  get-nettcpconnection get-netipaddress get-netadapter get-dnsclientcache get-timezone get-localuser get-localgroup
  foreach-object % select-string sls tee-object out-string start-sleep import-module ipmo new-variable set-variable sv
  set-alias sal set-strictmode push-location pushd pop-location popd set-location sl cd chdir cd.. clear-host cls
  measure-command
`)

/** Content readers: a credentials file, or a file outside the working directories, is classified. */
export const CONTENT_READERS = set('cat head tail less more type bat strings xxd hexdump od nl tac get-content gc')

/** Shell builtins and state that change nothing on disk. */
export const BUILTINS = set('cd pushd popd export unset set shopt alias unalias local declare typeset readonly let')

export const SHELLS = set('sh bash zsh dash ksh fish pwsh powershell cmd')
export const INTERPRETERS = set('python python3 py node deno bun ruby perl php rscript julia lua ts-node tsx')
export const PYTHON_MODULES_OK = set('pytest unittest mypy ruff black flake8 isort pylint pyflakes json.tool doctest compileall py_compile venv coverage pydoc pip tox nox build hatch')

/** Wrappers whose real command follows their own options. */
export const WRAPPERS = set('time nice nohup command builtin exec env timeout xargs watch stdbuf caffeinate ionice chronic unbuffer')

export const DELETERS = set('rm rmdir del erase rd unlink shred trash remove-item ri clear-content clc clear-item cli')
export const FILE_OPS = set(`
  mkdir md touch cp mv ln rename install tar zip unzip gzip gunzip bzip2 xz zstd 7z tee truncate split
  new-item ni copy-item cpi copy cp move-item mi move rename-item rni ren set-content sc add-content ac out-file
  export-csv export-clixml expand-archive compress-archive new-temporaryfile
`)
export const HTTP = set('curl wget iwr irm invoke-webrequest invoke-restmethod http https xh aria2c')
export const PERMS = set('chmod chown chgrp icacls attrib takeown set-acl')

/** Project tools: build, test, lint and format runners that work on the project in place. */
export const PROJECT_TOOLS = set(`
  tsc eslint prettier biome oxlint stylelint markdownlint shellcheck hadolint jest vitest mocha ava jasmine karma tap
  pytest ruff black mypy flake8 isort pylint pyright bandit rustfmt gofmt goimports golangci-lint staticcheck
  phpunit rspec rubocop ctest ninja swiftlint ktlint detekt playwright cypress nyc c8 tsup esbuild rollup webpack vite
  swc babel turbo nx lerna dotnet-format clang-format clang-tidy cppcheck cmake meson cargo-clippy cargo-fmt
  pre-commit lint-staged husky commitlint standard xo ts-prune knip depcheck madge jscpd
  coverage tox nox hatch
`)

/** Package-manager scripts run without a classifier. */
export const SAFE_SCRIPTS = set('test tests build lint typecheck type-check check format fmt compile coverage tsc prettier eslint lint:fix test:unit test:ci test:e2e validate verify ci')
