<!doctype html>
<html lang="en" dir="ltr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DataRiver</title>
  <link rel="stylesheet" href="${url.resourcesPath}/css/login.css">
</head>
<body>
  <main class="login-shell" aria-labelledby="login-title">
    <section class="login-card">
      <header class="login-brand">
        <div class="brand-mark" aria-hidden="true">✓</div>
        <h1 id="login-title">DataRiver</h1>
        <p>Integrated Data Catalog Platform</p>
      </header>

      <#if message?has_content>
        <div class="login-message login-message-${message.type}" role="alert">${kcSanitize(message.summary)?no_esc}</div>
      </#if>

      <form id="kc-form-login" action="${url.loginAction}" method="post">
        <label for="username">Email Address</label>
        <div class="field">
          <span aria-hidden="true">◉</span>
          <input id="username" name="username" type="text" value="${login.username!''}" autocomplete="username" placeholder="user@email.com" autofocus required>
        </div>

        <label for="password">Password</label>
        <div class="field">
          <span aria-hidden="true">⌑</span>
          <input id="password" name="password" type="password" autocomplete="current-password" placeholder="••••••••" required>
        </div>

        <#if realm.rememberMe && !usernameEditDisabled??>
          <label class="remember" for="rememberMe"><input id="rememberMe" name="rememberMe" type="checkbox"> ${msg("rememberMe")}</label>
        </#if>
        <input id="id-hidden-input" name="credentialId" type="hidden" <#if auth.selectedCredential??>value="${auth.selectedCredential}"</#if>>
        <button type="submit">Sign In <span aria-hidden="true">→</span></button>
      </form>

      <footer>DATARIVER · ${realm.displayName!"Secure Environment"}</footer>
    </section>
  </main>
</body>
</html>
