import { Amplify } from "aws-amplify";
import { confirmSignIn, fetchAuthSession, getCurrentUser, signIn, signOut } from "aws-amplify/auth";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { sessionStorage } from "aws-amplify/utils";

export interface AuthConfiguration {
  userPoolClientId: string;
  userPoolId: string;
}

export type SignInOutcome = "new_password_required" | "signed_in";

export interface AuthClient {
  confirmNewPassword(password: string): Promise<void>;
  getAccessToken(): Promise<string>;
  restoreSession(): Promise<boolean>;
  signIn(email: string, password: string): Promise<SignInOutcome>;
  signOut(): Promise<void>;
}

function requiredEnvironmentValue(environment: Record<string, unknown>, name: string): string {
  const value = environment[name];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${name} is required`);
  }
  return value.trim();
}

export function readAuthConfiguration(environment: Record<string, unknown>): AuthConfiguration {
  return {
    userPoolClientId: requiredEnvironmentValue(environment, "VITE_COGNITO_CLIENT_ID"),
    userPoolId: requiredEnvironmentValue(environment, "VITE_COGNITO_USER_POOL_ID"),
  };
}

function signInOutcome(result: {
  isSignedIn: boolean;
  nextStep: { signInStep: string };
}): SignInOutcome {
  if (result.isSignedIn || result.nextStep.signInStep === "DONE") {
    return "signed_in";
  }
  if (result.nextStep.signInStep === "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED") {
    return "new_password_required";
  }
  throw new Error("Unsupported Cognito sign-in challenge");
}

export function createCognitoAuthClient(configuration: AuthConfiguration): AuthClient {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolClientId: configuration.userPoolClientId,
        userPoolId: configuration.userPoolId,
      },
    },
  });
  cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage);

  return {
    async confirmNewPassword(password) {
      const result = await confirmSignIn({ challengeResponse: password });
      if (signInOutcome(result) !== "signed_in") {
        throw new Error("Cognito did not complete the new-password challenge");
      }
    },

    async getAccessToken() {
      const session = await fetchAuthSession();
      if (session.tokens?.accessToken === undefined) {
        throw new Error("No authenticated access token is available");
      }
      return session.tokens.accessToken.toString();
    },

    async restoreSession() {
      try {
        await getCurrentUser();
        return true;
      } catch {
        return false;
      }
    },

    async signIn(email, password) {
      return signInOutcome(await signIn({ username: email, password }));
    },

    async signOut() {
      await signOut();
    },
  };
}
