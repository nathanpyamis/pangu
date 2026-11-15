import datetime

from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class PartyProfile(models.Model):
    """
    Singleton: everything the public site says about the party lives here, so
    the secretariat can edit it in /admin/ without touching code.
    """
    name = models.CharField(max_length=80, default="Pangu Pati")
    short_name = models.CharField(max_length=30, default="Pangu")
    tagline = models.CharField(max_length=140, default="Pangu Next Generation")
    founded = models.DateField(null=True, blank=True, default=datetime.date(1967, 6, 13))
    election_name = models.CharField(max_length=120, default="2027 National General Election")
    election_date = models.DateField(
        null=True, blank=True,
        help_text="Polling start date. Turns on the home-page countdown and the candidate age check.",
    )
    rotating_lines = models.CharField(
        max_length=300, default="Pangu Next Generation|2027 National General Election|Join the movement",
        help_text="Lines that rotate under the party name, separated by |",
    )
    intro = models.CharField(
        max_length=300, blank=True,
        default="[Placeholder] One-sentence welcome for the home page.",
    )
    about = models.TextField(
        default="[Placeholder] The party's story, values and record. "
                "Separate paragraphs with a blank line.",
    )
    header_image = models.ImageField(
        upload_to="party/", blank=True,
        help_text="Leaders header for the home page. Leave empty to use the bundled image.",
    )
    header_caption = models.CharField(max_length=200, blank=True,
                                      help_text="Optional caption naming the leaders in the header image.")
    logo = models.ImageField(upload_to="party/", blank=True,
                             help_text="Leave empty to use the bundled Pangu Pati logo.")

    # Candidate intake
    applications_open = models.BooleanField(default=True)
    applications_close = models.DateField(null=True, blank=True,
                                          help_text="Last day to apply. Leave empty for no deadline.")
    signatory_name = models.CharField(max_length=120, blank=True,
                                      help_text="Signs endorsement letters.")
    signatory_title = models.CharField(max_length=120, blank=True, default="General Secretary")

    # Contact
    office_address = models.CharField(max_length=200, blank=True,
                                      default="[Placeholder] Party secretariat, Port Moresby")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    facebook_url = models.URLField(blank=True)
    tiktok_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    x_url = models.URLField("X / Twitter URL", blank=True)

    class Meta:
        verbose_name = "Party profile"
        verbose_name_plural = "Party profile"

    def __str__(self):
        return self.name

    @property
    def name_first(self):
        return self.name.split(" ", 1)[0]

    @property
    def name_rest(self):
        parts = self.name.split(" ", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def rotating_list(self):
        return [x.strip() for x in self.rotating_lines.split("|") if x.strip()]

    @property
    def about_paragraphs(self):
        return [p.strip() for p in self.about.split("\n\n") if p.strip()]

    @property
    def socials(self):
        pairs = [("facebook", self.facebook_url), ("tiktok", self.tiktok_url),
                 ("youtube", self.youtube_url), ("x", self.x_url)]
        return [{"name": n, "url": u} for n, u in pairs if u]

    @property
    def applications_are_open(self):
        if not self.applications_open:
            return False
        return self.applications_close is None or timezone.localdate() <= self.applications_close

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Leader(models.Model):
    """Leadership and National Executive profiles (About panel)."""
    name = models.CharField(max_length=120)
    title = models.CharField(max_length=120)
    photo = models.ImageField(upload_to="party/leaders/", blank=True)
    order = models.PositiveSmallIntegerField(default=10)
    is_visible = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.name} – {self.title}"


class NewsPost(models.Model):
    class Kind(models.TextChoices):
        NEWS = "NEWS", "News"
        PRESS = "PRESS", "Press release"
        RALLY = "RALLY", "Rally update"

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    kind = models.CharField(max_length=5, choices=Kind.choices, default=Kind.NEWS)
    summary = models.CharField(max_length=300, blank=True)
    body = models.TextField()
    cover_image = models.ImageField(upload_to="news/%Y/%m/", blank=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:220]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class PolicyDocument(models.Model):
    class Pillar(models.TextChoices):
        ECONOMY = "ECONOMY", "Economy"
        AGRICULTURE = "AGRICULTURE", "Agriculture"
        INFRASTRUCTURE = "INFRA", "Infrastructure"
        EDUCATION = "EDUCATION", "Education"
        HEALTH = "HEALTH", "Health"
        LAW_ORDER = "LAW_ORDER", "Law & Order"
        INTEGRAL_HUMAN_DEVELOPMENT = "INTEGRAL_HUMAN_DEVELOPMENT", "Integral Human Development"
        GOOD_GOVERNANCE = "GOOD_GOVERNANCE", "Good Governance"
        NATIONAL_UNITY = "NATIONAL_UNITY", "National Unity"
        SUSTAINABLE_DEVELOPMENT = "SUSTAINABLE_DEVELOPMENT","Sustainable Development"
        SELF_RELIANCE = "SELF_RELIANCE","Self-Reliance"

    pillar = models.CharField(max_length=30, choices=Pillar.choices)
    title = models.CharField(max_length=200)
    summary = models.TextField()
    pdf = models.FileField(upload_to="policies/", blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "pillar"]

    def __str__(self):
        return f"{self.get_pillar_display()}: {self.title}"

    @property
    def pillar_key(self):
        return self.pillar.lower()

    @property
    def pillar_label(self):
        return self.get_pillar_display()


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    phone_or_email = models.CharField(max_length=150)
    subject = models.CharField(max_length=150, blank=True)
    message = models.TextField(max_length=3000)
    received_at = models.DateTimeField(auto_now_add=True)
    is_handled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.name}: {self.subject or self.message[:40]}"
