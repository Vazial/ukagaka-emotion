# branch protection 設定手順

> 対象: リモートホスト(GitHub等)に本リポジトリを接続した後に、人間が実行する。
> 根拠: meta/guardrails.md 1節・2節。現時点(2026-07-13)ではリモート未接続のため、ここに手順を記録するに留める。

## 前提

- リモート: GitHub想定(`gh` CLIまたはWeb UIで設定)
- 保護対象ブランチ: `main`

## 設定項目

| 項目 | 設定値 |
|---|---|
| Require a pull request before merging | ON |
| Require approvals | 1以上(人間の承認) |
| Require status checks to pass before merging | ON — `L1: 実装の内部品質` `L2: 構造の健全性` `L3: 境界の整合` `L4: 仕様の充足`(.github/workflows/ci.yml のjob名)を必須チェックに指定 |
| Require branches to be up to date before merging | ON |
| Restrict who can push to matching branches | ON — 人間のみ許可。AIのgit操作用トークン/アカウントは含めない |
| Allow force pushes | OFF |
| Allow deletions | OFF |

## gh CLI での適用例(接続後に人間が実行)

```sh
gh api repos/:owner/:repo/branches/main/protection \
  --method PUT \
  -f required_pull_request_reviews[required_approving_review_count]=1 \
  -f required_status_checks[strict]=true \
  -f 'required_status_checks[contexts][]=L1: 実装の内部品質(単体テスト・lint)' \
  -f 'required_status_checks[contexts][]=L2: 構造の健全性(依存関係lint等)' \
  -f 'required_status_checks[contexts][]=L3: 境界の整合(契約テスト等)' \
  -f 'required_status_checks[contexts][]=L4: 仕様の充足(受け入れシナリオ実行)' \
  -f enforce_admins=true \
  -f allow_force_pushes=false \
  -f allow_deletions=false
```

CIのjob名を変更した場合は`required_status_checks[contexts]`も追従させること。

## CODEOWNERS

`steps/`・`dsl/`配下はtester成果物であり、reviewerの監査を経ての人間承認が必須(verification.md L4詳細(2))。
リモート接続後、`.github/CODEOWNERS`に以下を追加する:

```
/projects/reservation-system/**/steps/ @<承認者>
/projects/reservation-system/**/dsl/   @<承認者>
```
