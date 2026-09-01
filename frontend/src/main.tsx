import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { createApiClient, readApiConfiguration } from "./api";
import { createCognitoAuthClient, readAuthConfiguration } from "./auth";
import "./index.css";

const rootElement = document.querySelector<HTMLDivElement>("#root");

if (rootElement === null) {
  throw new Error("Unable to find the root element");
}

const auth = createCognitoAuthClient(readAuthConfiguration(import.meta.env));
const api = createApiClient(readApiConfiguration(import.meta.env), auth);

createRoot(rootElement).render(
  <StrictMode>
    <App api={api} auth={auth} />
  </StrictMode>,
);
