/**
 * The live-call server log showed `GET /favicon.ico 404`: the page declared no icon, so the
 * browser guessed. Declaring one stops the guess.
 */
import { describe, expect, it } from 'vitest'
import html from '../index.html?raw'
import svg from '../public/favicon.svg?raw'

describe('favicon', () => {
  it('is declared in the document head', () => {
    expect(html).toMatch(/<link rel="icon" type="image\/svg\+xml" href="\/favicon\.svg" \/>/)
    expect(html).toMatch(/rel="alternate icon"/)
  })

  it('is a real drawing in public/, so the build copies it to the site root', () => {
    expect(svg).toMatch(/^<svg[^>]*viewBox="0 0 32 32"/)
    expect(svg).toContain('</svg>')
    // Drawn, not a letter: the same dip-and-recover line the Timeline draws.
    expect(svg).toMatch(/<path/)
  })
})
