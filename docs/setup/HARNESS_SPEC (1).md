# 参照した公式資料

確認日: 2026-10-30。以下は指示書の根拠となる資料。プロジェクト固有のAPI、分担、gate構成は本パックの設計判断。

## Codex

- AGENTS.mdの適用: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- サブエージェント: https://learn.chatgpt.com/docs/agent-configuration/subagents
- Git worktrees: https://learn.chatgpt.com/docs/environments/git-worktrees
- WSL: https://learn.chatgpt.com/docs/windows/wsl
- 実行計画と記録の設計例: https://developers.openai.com/cookbook/articles/codex_exec_plans
- 開発ハーネスの構成例: https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex

AGENTS.mdはCodexが読む規約。PLANやhandoff/gates.jsonはこのプロジェクトで明示的に読む・実行する規約であり、Codexが自動解釈する標準設定ではない。サブエージェントの利用可否は手元のクライアントで確認する。

## WSL / Docker / kind

- Docker Desktop WSL2: https://docs.docker.com/desktop/features/wsl/
- Linux filesystem/bind mount推奨: https://docs.docker.com/desktop/features/wsl/best-practices/
- WSL network: https://learn.microsoft.com/en-us/windows/wsl/networking
- kind configuration: https://kind.sigs.k8s.io/docs/user/configuration/
- kind on WSL2: https://kind.sigs.k8s.io/docs/user/using-wsl2/
- Docker Engine Ubuntu: https://docs.docker.com/engine/install/ubuntu/
- Docker権限: https://docs.docker.com/engine/install/linux-postinstall/
- Docker CLI環境変数の優先順位: https://docs.docker.com/reference/cli/docker/
- Docker contextとendpoint: https://docs.docker.com/engine/manage-resources/contexts/
- Desktop利用条件: https://docs.docker.com/subscription-billing/desktop-license/

## Kubernetes / PostgreSQL

- Pod内からAPI接続: https://kubernetes.io/docs/tasks/run-application/access-api-from-pod/
- NetworkPolicy/CNIの条件: https://kubernetes.io/docs/concepts/services-networking/network-policies/
- Application security checklist: https://kubernetes.io/docs/concepts/security/application-security-checklist/
- Queue-like tableとSKIP LOCKED: https://www.postgresql.org/docs/current/sql-select.html

## 後続Azure設計

- AKS Pod sandboxing: https://learn.microsoft.com/en-us/azure/aks/use-pod-sandboxing
- Isolationの範囲: https://learn.microsoft.com/en-us/azure/aks/concepts-pod-sandboxing

Pod sandboxingだけでstorage/network/管理者操作まで分離できるとは扱わない。Azureの実環境作成は今回の実装対象外。
