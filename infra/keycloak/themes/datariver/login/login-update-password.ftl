<#import "password-commons.ftl" as passwordCommons>
<!doctype html>
<html lang="${(locale.currentLanguageTag)!'ko'}" dir="ltr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DataRiver · ${msg("updatePasswordTitle")}</title>
  <link rel="stylesheet" href="${url.resourcesPath}/css/login.css">
</head>
<body>
  <main class="login-shell" aria-labelledby="password-title">
    <section class="login-card">
      <header class="login-brand">
        <div class="brand-mark" aria-hidden="true">✓</div>
        <h1>DataRiver</h1>
        <p id="password-title">${msg("updatePasswordTitle")}</p>
      </header>

      <#if message?has_content && !messagesPerField.existsError('password','password-confirm')>
        <div class="login-message login-message-${message.type}" role="alert">${kcSanitize(message.summary)?no_esc}</div>
      </#if>

      <form id="kc-passwd-update-form" action="${url.loginAction}" method="post">
        <label for="password-new">${msg("passwordNew")}</label>
        <div class="field">
          <span aria-hidden="true">⌑</span>
          <input id="password-new" name="password-new" type="password" autocomplete="new-password" autofocus required
                 aria-invalid="<#if messagesPerField.existsError('password')>true<#else>false</#if>">
        </div>
        <#if messagesPerField.existsError('password')>
          <div class="field-error" id="input-error-password" role="alert">${kcSanitize(messagesPerField.get('password'))?no_esc}</div>
        </#if>

        <label for="password-confirm">${msg("passwordConfirm")}</label>
        <div class="field">
          <span aria-hidden="true">⌑</span>
          <input id="password-confirm" name="password-confirm" type="password" autocomplete="new-password" required
                 aria-invalid="<#if messagesPerField.existsError('password-confirm')>true<#else>false</#if>">
        </div>
        <#if messagesPerField.existsError('password-confirm')>
          <div class="field-error" id="input-error-password-confirm" role="alert">${kcSanitize(messagesPerField.get('password-confirm'))?no_esc}</div>
        </#if>

        <@passwordCommons.logoutOtherSessions/>
        <div class="form-actions">
          <button name="login" type="submit">${msg("doSubmit")} <span aria-hidden="true">→</span></button>
          <#if isAppInitiatedAction??>
            <button class="button-secondary" name="cancel-aia" type="submit" value="true">${msg("doCancel")}</button>
          </#if>
        </div>
      </form>

      <footer>DATARIVER · ${realm.displayName!"Secure Environment"}</footer>
    </section>
  </main>
</body>
</html>
