import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { createCognitoAuthClient, readAuthConfiguration } from "./auth";
import "./index.css";

const rootElement = document.querySelector<HTMLDivElement>("#root");

if (rootElement === null) {
  throw new Error("Unable to find the root element");
}

const auth = createCognitoAuthClient(readAuthConfiguration(import.meta.env));

createRoot(rootElement).render(
  <StrictMode>
    <App auth={auth} />
  </StrictMode>,
);
