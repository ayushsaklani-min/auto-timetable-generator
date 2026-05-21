import { cp, rm } from 'node:fs/promises'
import { resolve } from 'node:path'

const rootDist = resolve('dist')
const frontendDist = resolve('frontend', 'dist')

await rm(rootDist, { recursive: true, force: true })
await cp(frontendDist, rootDist, { recursive: true })
