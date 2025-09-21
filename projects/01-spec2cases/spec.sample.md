# ログイン機能

## LGN-001 正常ログイン
- pre: ユーザー alice が存在する
- step: ログイン画面にアクセス
- step: ID/PWを入力
- step: ログインを押下
- expected: ダッシュボードに遷移
- expected: Welcome Alice が表示
- tag: happy-path
- tag: smoke

## LGN-002 パスワード誤り
- pre: ユーザー alice が存在する
- step: ログイン画面にアクセス
- step: ID=alice, PW=wrong を入力
- step: ログインを押下
- expected: エラートースト 'Invalid credentials'
- tag: negative
