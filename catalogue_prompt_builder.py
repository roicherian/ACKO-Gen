"""Vehicle catalogue prompt builder module."""

class ConfigurationError(Exception):
    """Configuration error in prompt building."""
    pass

def build_prompt(variant_id, color=None, custom_prompt=None):
    """Build a prompt for a vehicle variant."""
    return {
        "prompt": f"A photorealistic image of a vehicle in {color or 'default color'}",
        "variant_id": variant_id
    }
