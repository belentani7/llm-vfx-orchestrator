import type { Plugin } from "opencode"

/**
 * BELENTANI // MAGIC PLUGIN
 * signature: belentani.eu / noiacore.com
 *
 * Adds an /immersive command that points the user to the magic layer,
 * and a session hook that keeps the signature in mind.
 */
export const magic: Plugin = async ({ project, hooks }) => {
  const repo = project.directory.split(/[\\/]/).pop() ?? "node"

  project.command("immersive", {
    description: "Open the BELENTANI magic experience for this node",
    async run() {
      const { exec } = await import("node:child_process")
      const { promisify } = await import("node:util")
      const pex = promisify(exec)
      const target = "magic/immersive.html"
      try {
        if (process.platform === "win32") {
          await pex(`start "" "${target}"`)
        } else if (process.platform === "darwin") {
          await pex(`open "${target}"`)
        } else {
          await pex(`xdg-open "${target}"`)
        }
      } catch (e) {
        return `Unable to open ${target}: ${String(e)}`
      }
      return `Immersed in ${repo}. belentani.eu / noiacore.com`
    },
  })

  hooks.notify = async (event) => {
    if (event.type === "session.idle") {
      // keep the signature warm
    }
  }

  return () => {}
}
